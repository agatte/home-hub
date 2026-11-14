"""Inactive Linux ProtectedVerifyIO. Only trusted server composition may inject.

No settings/env/bootstrap wiring. Root custody proof provider and independent
generation/revision observer are still absent; this is not release readiness.
"""
import asyncio
import math
import socket
import stat
import struct
import sys

from security.homehub_identity_broker.linux_protected_verify import (
    RootCustodyProof, VERIFY_PATH, protected_path, validate_policy,
)
from .identity_broker_verify_client import ProtocolDenied, decode_frame, read_frame


class LinuxProtectedVerifyIO:
    def __init__(self, policy, *, proof, timeout=0.5, capacity=8):
        if (sys.platform != "linux" or type(proof) is not RootCustodyProof
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 2 or type(capacity) is not int or not 1 <= capacity <= 32):
            raise ProtocolDenied()
        validate_policy(policy)
        self._policy, self._proof = policy, proof
        self._timeout, self._capacity, self._active = timeout, capacity, 0
        self._chain = self._check()

    def __repr__(self):
        return "<LinuxProtectedVerifyIO inactive>"

    def _check(self):
        self._proof.check(role="backend", policy=self._policy)
        p = self._policy
        chain = protected_path(VERIFY_PATH, uid=0, gid=p.backend_gid, mode=0o660,
            kind=stat.S_ISSOCK, identity=p.listener.path_identity)
        if hasattr(self, "_chain") and chain != self._chain:
            raise ProtocolDenied()
        return chain

    async def exchange_verify(self, request: bytes) -> bytes:
        try:
            if decode_frame(request).get("method") != "verify" or self._active >= self._capacity:
                raise ProtocolDenied()
            self._active += 1
            try:
                return await asyncio.wait_for(self._exchange(request), self._timeout)
            finally:
                self._active -= 1
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        raise ProtocolDenied()  # no raw exception/cause/context survives

    async def _exchange(self, request):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.setblocking(False)
        loop = asyncio.get_running_loop()
        try:
            self._check()
            await loop.sock_connect(connection, VERIFY_PATH)
            pid, uid, gid = struct.unpack("iII", connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")))
            if (pid, uid, gid) != self._policy.creator_peer:
                raise ProtocolDenied()
            self._check()  # Authenticate peer AND revalidate namespace before token bytes.
            await loop.sock_sendall(connection, request)
            connection.shutdown(socket.SHUT_WR)

            async def exact(count):
                result = bytearray()
                while len(result) < count:
                    part = await loop.sock_recv(connection, count - len(result))
                    if not part:
                        raise ProtocolDenied()
                    result.extend(part)
                return bytes(result)

            response = await read_frame(exact)
            if await loop.sock_recv(connection, 1):
                raise ProtocolDenied()
            self._check()
            decode_frame(response)
            return response
        finally:
            connection.close()
