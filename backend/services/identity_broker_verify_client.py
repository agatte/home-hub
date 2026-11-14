"""Inactive v1 verify contract. No socket connector, settings, store or admin API.

Only reviewed composition may inject ProtectedVerifyIO. That adapter MUST prove
Linux root-controlled pathname/ancestors/ACL custody and kernel SO_PEERCRED of
the dedicated broker (including replacement races); Windows cannot prove this.
One connection/request, no reuse/retry or loopback fallback. The adapter must
bound reads BEFORE allocation and close/reap on every path. This module is not
deployable until such an adapter and the separately protected broker exist.
"""
import asyncio
import inspect
import json
import math
import re
import secrets
import struct
import time
from typing import Protocol

from backend.identity_core import Identity
from backend.identity_policy import PROFILES
from backend.services.ws_authenticated_boundary import TrustedAsyncAuthorizer

VERSION = 1
MAX_FRAME = 2048
TOKEN = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}\Z")
HEX = re.compile(r"[0-9a-f]{32}\Z")
DENIALS = frozenset({"denied", "revoked", "quarantined", "unavailable", "error", "expired"})


class ProtocolDenied(ValueError):
    def __init__(self):
        super().__init__("Broker contract denied")


class ProtectedVerifyIO(Protocol):
    async def exchange_verify(self, request: bytes) -> bytes:
        """Return exactly one bounded length-prefixed frame, after peer proof.

        No raw request/response, exceptions, credentials or locals may be logged.
        The future broker must serialize verify with revocation/rotation/restore,
        check its independent journal/floor, and never echo verifier input.
        """
        ...


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolDenied()
        result[key] = value
    return result


def encode_frame(value: dict) -> bytes:
    try:
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("ascii")
        if not 1 <= len(body) <= MAX_FRAME:
            raise ProtocolDenied()
        return struct.pack("!I", len(body)) + body
    except Exception:
        pass
    raise ProtocolDenied()  # outside handler: no sensitive exception context


def decode_frame(frame: bytes) -> dict:
    """Four-byte unsigned big-endian length, ASCII JSON, exact EOF; no extras."""
    try:
        if type(frame) is not bytes or not 5 <= len(frame) <= MAX_FRAME + 4:
            raise ProtocolDenied()
        length = struct.unpack("!I", frame[:4])[0]
        if not 1 <= length <= MAX_FRAME or length != len(frame) - 4:
            raise ProtocolDenied()
        value = json.loads(frame[4:].decode("ascii"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ProtocolDenied()))
        if type(value) is not dict:
            raise ProtocolDenied()
        return value
    except Exception:
        pass
    raise ProtocolDenied()


async def read_frame(readexactly) -> bytes:
    """Bounded stream helper for a future adapter; caller owns EOF and deadline."""
    try:
        header = await readexactly(4)
        if type(header) is not bytes or len(header) != 4:
            raise ProtocolDenied()
        length = struct.unpack("!I", header)[0]
        if not 1 <= length <= MAX_FRAME:
            raise ProtocolDenied()
        body = await readexactly(length)
        if type(body) is not bytes or len(body) != length:
            raise ProtocolDenied()
        return header + body
    except Exception:
        pass
    raise ProtocolDenied()


def valid_hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def valid_time(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1e12


class VerifyClient:
    """Bounded async Identity-or-None callback, suitable for TrustedAsyncAuthorizer.

    generation()/revision() supply trusted, nonblocking CURRENT broker state
    fences, never values inferred from HTTP or this response. Revision changes
    on EVERY security mutation; generation changes on restore. A separately
    reviewed protected state observer is required; static snapshots are unsafe.
    Read skew denies. This does not revoke an already started actuator write.
    No grant/secret cache. Denial statuses
    intentionally collapse to None outside the wire parser. Late results never
    grant; their capacity is retained until actual I/O completion, even if the
    adapter ignores cancellation. Anonymous admission cannot consume active slots.
    """

    def __init__(self, io: ProtectedVerifyIO, *, generation, revision, timeout=1.0,
                 active_capacity=16, clock=time.time):
        if not inspect.iscoroutinefunction(getattr(io, "exchange_verify", None)):
            raise TypeError("Explicit protected async verify I/O required")
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 5 or type(active_capacity) is not int
                or not 1 <= active_capacity <= 64 or not callable(generation)
                or not callable(revision)):
            raise ValueError("Invalid verify configuration")
        self._io, self._generation, self._clock = io, generation, clock
        self._revision = revision
        self._timeout = timeout
        self._limits = {"admission": 1, "active": active_capacity}
        self._pending = {"admission": set(), "active": set()}

    def __repr__(self):
        return "<VerifyClient inactive-injection-contract>"

    def authorizer(self) -> TrustedAsyncAuthorizer:
        return TrustedAsyncAuthorizer(self.authorize)

    async def authorize(self, token, operation, *, lane, stage, claimed_source=None) -> Identity | None:
        # All operation/lane/stage inputs belong to server adapters, not clients.
        if (type(token) is not str or TOKEN.fullmatch(token) is None
                or type(operation) is not str or type(lane) is not str
                or type(stage) is not str or stage not in self._limits
                or claimed_source is not None
                or not any((operation, lane) in p.grants for p in PROFILES.values())):
            return None
        pending = self._pending[stage]
        if len(pending) >= self._limits[stage]:
            return None
        try:
            generation = self._generation()
            revision = self._revision()
            if (not valid_hex(generation) or type(revision) is not int
                    or not 0 <= revision <= 2**53 - 1):
                return None
            nonce = secrets.token_hex(16)
            request = encode_frame({"version": VERSION, "method": "verify", "nonce": nonce,
                                    "token": token, "operation": operation, "lane": lane,
                                    "generation": generation, "revision": revision})
            start = time.monotonic()
            task = asyncio.create_task(self._io.exchange_verify(request))
            pending.add(task)

            def settled(done):
                pending.discard(done)
                if not done.cancelled():
                    done.exception()  # consume only; never log sensitive adapter errors
            task.add_done_callback(settled)
            done, _ = await asyncio.wait({task}, timeout=self._timeout)
            if not done or time.monotonic() - start > self._timeout:
                return None
            response = decode_frame(task.result())
            base = {"version", "nonce", "status", "generation", "revision"}
            if (type(response.get("version")) is not int or response["version"] != VERSION
                    or response.get("nonce") != nonce
                    or response.get("generation") != generation
                    or type(response.get("revision")) is not int
                    or response["revision"] != revision
                    or self._generation() != generation or self._revision() != revision):
                return None
            status = response.get("status")
            if type(status) is not str:
                return None
            if status in DENIALS:
                if response.keys() != base:
                    return None
                return None
            if status != "verified" or response.keys() != base | {
                    "principal_id", "profile", "source", "lane", "operation", "kind", "expires_at"}:
                return None
            profile = response["profile"]
            if type(profile) is not str or profile not in PROFILES:
                return None
            policy = PROFILES[profile]
            kind = "browser_session" if profile in {"owner_browser", "kiosk"} else "native_bearer"
            now = self._clock()
            if (not valid_hex(response["principal_id"]) or response["source"] != policy.source
                    or response["lane"] != lane or response["operation"] != operation
                    or (operation, lane) not in policy.grants or response["kind"] != kind
                    or not valid_time(response["expires_at"]) or not valid_time(now)
                    or response["expires_at"] <= now):
                return None
            return Identity(response["principal_id"], profile, policy.source, lane)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None  # never expose adapter exception/cause or raw response
