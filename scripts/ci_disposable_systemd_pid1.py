"""TEST-ONLY / DO-NOT-INSTALL: genuine PID1 experiment on a disposable CI VM.

No production imports, attestation, RootCustodyProof or trusted loader closure.
Environment checks prevent accidental execution; they are not OS attestation.
The root runner and synthetic fresh-generation oracle are trusted test fixtures.
Alternate ports/manual launches, IPv6, malicious root and mount/ABA races remain.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys


PYTHON = "/usr/bin/python3"
SYSTEMCTL = "/usr/bin/systemctl"
BRANCH = "work/461-integrated-release-candidate-20261114"

# Fixed source and paths substituted by this runner, never a CLI path selector.
GUARD = r'''
import hashlib, json, os, stat, sys
from pathlib import Path
root = Path(ROOT)
def metadata(path, mode, directory=False):
    s = path.lstat()
    assert (stat.S_ISDIR if directory else stat.S_ISREG)(s.st_mode)
    assert s.st_uid == s.st_gid == 0
    assert stat.S_IMODE(s.st_mode) == mode
    assert directory or s.st_nlink == 1
def read(path, mode):
    metadata(path, mode)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        assert s == path.lstat() and s.st_size < 65536
        return os.read(fd, 65536)
    finally:
        os.close(fd)
def uint(v):
    return type(v) is int and 0 <= v < 2**64
try:
    assert os.geteuid() == 0
    metadata(Path('/'), 0o755, True)
    metadata(Path('/run'), 0o755, True)
    metadata(root, 0o755, True)
    metadata(root / 'policy', 0o700, True)
    floor = json.loads(read(root / 'policy/floor', 0o400))
    approval = json.loads(read(root / 'policy/approval', 0o400))
    candidate = json.loads(read(root / 'policy/candidate', 0o400))
    assert set(floor) == {'epoch', 'generation'}
    assert all(uint(v) for v in floor.values())
    assert floor == {'epoch': 7, 'generation': GENERATION}
    for record in (approval, candidate):
        assert set(record) == {'epoch', 'generation', 'sha256'}
        assert uint(record['epoch']) and uint(record['generation'])
        assert type(record['sha256']) is str
        assert len(record['sha256']) == 64
        assert all(c in '0123456789abcdef' for c in record['sha256'])
    assert candidate == approval
    assert candidate['epoch'] >= floor['epoch']
    assert candidate['generation'] == floor['generation']
    assert hashlib.sha256(read(root / 'mock-server.py', 0o555)).hexdigest() == candidate['sha256']
except Exception:
    sys.exit(23)
'''

SERVER = r'''
import os, socket
assert os.geteuid() == os.getuid() == 65534
assert os.getegid() == os.getgid() == 65534
assert set(os.getgroups()) - {65534} == set()
assert os.environ['LISTEN_PID'] == str(os.getpid())
assert os.environ['LISTEN_FDS'] == '1'
listener = socket.socket(fileno=3)
assert listener.family == socket.AF_INET
assert listener.getsockname() == ('127.0.0.1', TEST_PORT_LITERAL)
assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0
while True:
    client, _ = listener.accept()
    with client:
        client.settimeout(2)
        client.sendall(b'nonroot-systemd-fd3')
'''

LEGACY = r'''
import errno, socket, sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    if sys.argv[2] != 'plain':
        s.setsockopt(socket.SOL_SOCKET, getattr(socket, sys.argv[2]), 1)
    try:
        s.bind((sys.argv[3], int(sys.argv[1])))
    except OSError as e:
        sys.exit(0 if e.errno == errno.EADDRINUSE else 2)
    sys.exit(1)
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True,
                          timeout=15, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def ctl(*args, check=True):
    return command(SYSTEMCTL, "--system", *args, check=check)


def create(path, data, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        os.fchmod(stream.fileno(), mode)
        os.fchown(stream.fileno(), 0, 0)


def main():
    require(len(sys.argv) == 1, "no CLI arguments allowed")
    expected = {"HOMEHUB_DISPOSABLE_SYSTEMD_PID1": "1", "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": "agatte/home-hub", "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_HEAD_REF": BRANCH, "RUNNER_ENVIRONMENT": "github-hosted"}
    require(all(os.environ.get(k) == v for k, v in expected.items()), "CI guard denied")
    require(sys.platform == "linux" and os.geteuid() == 0, "disposable Linux root required")
    require(Path('/proc/1/comm').read_text().strip() == 'systemd'
            and Path('/run/systemd/system').is_dir(), "genuine systemd PID1 required")
    release = Path('/etc/os-release').read_text().splitlines()
    require('ID=ubuntu' in release and 'VERSION_ID="24.04"' in release, "Ubuntu 24.04 required")
    runid, attempt = (os.environ.get(k, '') for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
    require(all(re.fullmatch(r'[1-9][0-9]{0,19}', v) for v in (runid, attempt)), "numeric run required")
    prefix = f'homehub-test-287-{runid}-{attempt}'
    root = Path('/run') / prefix
    units = [Path('/run/systemd/system') / (prefix + suffix) for suffix in ('.socket', '.service')]
    for path in [root, *units]:
        require(not os.path.lexists(path), "test path collision")
    for unit in units:
        require(ctl('show', unit.name, '-p', 'LoadState', '--value').stdout.strip() == 'not-found',
                "existing manager unit collision")
    # Reserve only a kernel-selected IPv4 loopback port, then release for PID1.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    require(port != 8000, "production port forbidden")
    generation = int(runid) * 100000 + int(attempt)
    require(generation < 2**64, "generation out of range")
    server = SERVER.replace('TEST_PORT_LITERAL', str(port)).encode()
    approved = {'epoch': 7, 'generation': generation, 'sha256': hashlib.sha256(server).hexdigest()}
    floor = {'epoch': 7, 'generation': generation}
    created_units = []
    created_files = []
    created_root = False
    created_policy = False
    try:
        root.mkdir(mode=0o755)
        created_root = True
        root.chmod(0o755)
        (root / 'policy').mkdir(mode=0o700)
        created_policy = True

        def file(name, data, mode):
            path = root / name
            create(path, data, mode)
            created_files.append(path)

        def record(name, value):
            path = root / 'policy' / name
            # Replacing only our known fixture; never follow a substituted link.
            if path in created_files and os.path.lexists(path):
                path.unlink()
            file('policy/' + name, json.dumps(value).encode(), 0o400)

        file('mock-server.py', server, 0o555)
        file('mock-guard.py', GUARD.replace('ROOT', repr(str(root))).replace(
            'GENERATION', str(generation)).encode(), 0o400)
        for name, value in [('floor', floor), ('approval', approved), ('candidate', approved)]:
            record(name, value)
        socket_unit = f'''[Socket]
ListenStream=127.0.0.1:{port}
Accept=no
ReusePort=no
FreeBind=no
Service={prefix}.service
'''
        service_unit = f'''[Unit]
# Test repeatedly exercises failed starts: do not confuse start-rate limits
# with actual negative admission by the root pre-start guard.
StartLimitIntervalSec=0
Requires={prefix}.socket
After={prefix}.socket

[Service]
Type=exec
User=nobody
Group=nogroup
Sockets={prefix}.socket
SupplementaryGroups=
ExecStartPre=+{PYTHON} -I -S {root}/mock-guard.py
ExecStart={PYTHON} -I -S {root}/mock-server.py
Restart=no
TimeoutStartSec=10
TimeoutStopSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_INET AF_UNIX
'''
        for path, content in zip(units, (socket_unit, service_unit)):
            create(path, content.encode(), 0o644)
            created_units.append(path)
        ctl('daemon-reload')
        for path in units:
            require(ctl('show', path.name, '-p', 'FragmentPath', '--value').stdout.strip() == str(path),
                    'unexpected effective unit fragment')
            require(ctl('show', path.name, '-p', 'DropInPaths', '--value').stdout.strip() == '',
                    'unexpected drop-in')
        ctl('start', units[0].name)

        def held():
            require(ctl('is-active', units[0].name).stdout.strip() == 'active', 'socket lost')
            for host in ('127.0.0.1', '0.0.0.0'):
                for option in ('plain', 'SO_REUSEADDR', 'SO_REUSEPORT'):
                    command(PYTHON, '-I', '-S', '-c', LEGACY, str(port), option, host)

        def success():
            ctl('reset-failed', units[1].name)
            ctl('start', units[1].name)
            with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                client.settimeout(5)
                received = b''
                while len(received) < len(b'nonroot-systemd-fd3'):
                    chunk = client.recv(64)
                    require(bool(chunk), 'nonroot response truncated')
                    received += chunk
                require(received == b'nonroot-systemd-fd3', 'nonroot response missing')
            held()

        held()
        success()
        for _ in range(2):
            ctl('stop', units[1].name)
            held()
            success()
        cases = ('rollback', 'stale-generation', 'stale-floor', 'digest', 'missing-floor',
                 'writable-policy', 'untrusted-policy', 'boolean-epoch', 'symlink', 'hardlink')
        for case in cases:
            ctl('stop', units[1].name)
            record('floor', floor)
            record('candidate', approved)
            candidate = root / 'policy/candidate'
            if case in ('rollback', 'stale-generation', 'digest', 'boolean-epoch'):
                key, value = {'rollback': ('epoch', 6), 'stale-generation': ('generation', generation - 1),
                              'digest': ('sha256', '0' * 64), 'boolean-epoch': ('epoch', True)}[case]
                # Keep approval and candidate equal so the deeper floor/type/digest
                # checks are exercised, not merely the earlier equality check.
                invalid = {**approved, key: value}
                record('approval', invalid)
                record('candidate', invalid)
            elif case == 'missing-floor':
                (root / 'policy/floor').unlink()
            elif case == 'stale-floor':
                record('floor', {**floor, 'generation': generation - 1})
            elif case == 'writable-policy':
                (root / 'policy').chmod(0o777)
            elif case == 'untrusted-policy':
                os.chown(root / 'policy', 65534, 65534)
            elif case == 'symlink':
                candidate.unlink()
                candidate.symlink_to(root / 'policy/approval')
            elif case == 'hardlink':
                candidate.unlink()
                os.link(root / 'policy/approval', candidate)
            for action in ('start', 'restart'):
                ctl('reset-failed', units[1].name)
                require(ctl(action, units[1].name, check=False).returncode != 0, 'invalid start admitted')
                pre = ctl('show', units[1].name, '-p', 'ExecStartPre', '--value').stdout
                require('status=23' in pre, 'failure was not the root guard denial')
                require(ctl('show', units[1].name, '-p', 'MainPID', '--value').stdout.strip() == '0',
                        'backend running despite guard denial')
                held()
            os.chown(root / 'policy', 0, 0)
            (root / 'policy').chmod(0o700)
            record('approval', approved)
            record('candidate', approved)
            record('floor', floor)
            success()
            print(f'PASS {case}: root pre-start denial, retained PID1 socket, recovered', flush=True)
        print('PASS genuine systemd PID1 disposable IPv4 test; no production acceptance')
    finally:
        # Only exact paths created above; no glob, recursive removal or foreign unit stop.
        errors = []
        for path in reversed(created_units):
            try:
                ctl('stop', path.name)
            except Exception as error:
                errors.append(error)
        if not errors:
            for path in created_units:
                path.unlink()
            for path in dict.fromkeys(created_files):
                if os.path.lexists(path):
                    path.unlink()
            if created_policy:
                (root / 'policy').rmdir()
            if created_root:
                root.rmdir()
        if created_units:
            ctl('daemon-reload')
        require(not errors, 'exact-unit cleanup failed; VM must be decommissioned')


if __name__ == '__main__':
    main()
