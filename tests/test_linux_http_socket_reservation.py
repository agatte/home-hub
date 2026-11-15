"""Disposable Linux TCP custody mechanics; NO PID1/root proof is asserted.

Only AF_INET loopback ephemeral listening sockets are exercised; separate legacy
bind attempts cover loopback and IPv4 wildcard. IPv6, alternate routes, identity
provenance and independent launch-floor enforcement are NOT proved.
"""
import errno
from pathlib import Path
import socket
import subprocess
import sys

import pytest


LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux TCP/pass_fds kernel semantics")
CHILD = """
import socket, sys
with socket.socket(fileno=int(sys.argv[1])) as listener:
    listener.settimeout(3)
    with listener.accept()[0] as client:
        client.settimeout(3)
        client.sendall(b'held')
"""
LEGACY = """
import errno, socket, sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
    option = sys.argv[2]
    if option != 'none':
        candidate.setsockopt(socket.SOL_SOCKET, getattr(socket, option), 1)
    try:
        candidate.bind((sys.argv[3], int(sys.argv[1])))
    except OSError as error:
        sys.exit(0 if error.errno == errno.EADDRINUSE else 2)
    sys.exit(1)
"""


def test_inert_socket_fragment():
    source = (Path(__file__).resolve().parents[1] / "security" /
              "homehub_identity_broker" / "home-hub-http.socket.in").read_text()
    active = [line.strip() for line in source.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert active == ["[Socket]", "Accept=no", "ReusePort=no", "FreeBind=no"]
    assert "DO-NOT-INSTALL" in source
    assert "ListenStream unresolved" in source


def _legacy(address, option, bind_host):
    # Separate interpreter: no inherited reservation, no backend imports or config.
    result = subprocess.run([sys.executable, "-I", "-B", "-c", LEGACY,
                             str(address[1]), option, bind_host], close_fds=True,
                            capture_output=True, timeout=5, check=False)
    assert result.returncode == 0, (result.returncode, result.stderr)


def _accept_once(manager):
    with subprocess.Popen([sys.executable, "-I", "-B", "-c", CHILD,
                           str(manager.fileno())], pass_fds=(manager.fileno(),),
                          close_fds=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as child:
        try:
            with socket.create_connection(manager.getsockname(), timeout=3) as client:
                received = b""
                while len(received) <= 4:
                    chunk = client.recv(5 - len(received))
                    if not chunk:
                        break
                    received += chunk
                assert received == b"held"
            _, errors = child.communicate(timeout=5)
            assert child.returncode == 0, errors
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


@LINUX
@pytest.mark.parametrize("option", ["none", "SO_REUSEADDR", "SO_REUSEPORT"])
@pytest.mark.parametrize("bind_host", ["127.0.0.1", "0.0.0.0"])
def test_manager_reserves_across_child_restarts(option, bind_host):
    # Linux must provide SO_REUSEPORT; absence fails instead of weakening coverage.
    assert hasattr(socket, "SO_REUSEPORT")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as manager:
        assert manager.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        assert manager.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0
        manager.bind(("127.0.0.1", 0))
        assert manager.getsockname()[1] != 8000
        manager.listen(4)
        address = manager.getsockname()
        _legacy(address, option, bind_host)
        for _ in range(2):
            _accept_once(manager)
            _legacy(address, option, bind_host)  # child exited; manager never relinquished FD
    # Accepted connections may leave TIME_WAIT; release is separately tested below
    # without connections so SO_REUSEADDR cannot disguise a remaining listener.


@LINUX
def test_last_descriptor_controls_release():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as manager:
        manager.bind(("127.0.0.1", 0))
        assert manager.getsockname()[1] != 8000
        manager.listen(1)
        address = manager.getsockname()
        with manager.dup() as independent_copy:
            manager.close()
            assert independent_copy.getsockname() == address
            _legacy(address, "none", "127.0.0.1")
        # No connections/TIME_WAIT, no reuse fallback, no retry to mask a race.
        # Unrelated processes can race this ephemeral port: any such race fails.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as released:
            released.bind(address)
            released.listen(1)
