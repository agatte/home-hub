"""Fictional OFFLINE contract only; no artist payload or transport.

Caller-provided principal/audience/boot fields DO NOT establish human identity,
server identity, or TLS. No UI integration, persistence, background purge, or API.
Default randomness is requested only when issuing a challenge, never on import.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
from threading import Lock
from time import monotonic
from typing import Callable


class OfflineRefused(Exception):
    """Fixed error without caller input."""

    def __init__(self) -> None:
        super().__init__("Offline attempt refused")


@dataclass(frozen=True, repr=False)
class OfflineChallenge:
    token: str
    revision: int

    def __repr__(self) -> str:
        return "OfflineChallenge(<redacted>)"


class OfflineHandoffGate:
    """One fictional session, one challenge, one attempt; all transitions locked.

    Event calls must come from every selection/action/source reload/discard
    callback, including restoration to an earlier value. This class cannot
    observe a GUI or authenticate its caller. Construct a new session for a new
    deliberate attempt; never retry an old session after an ambiguous outcome.
    Injected clock must be trusted, finite and monotonic. Test token injection
    is for fictional tests ONLY. No real names belong in any argument.
    """

    def __init__(self, *, session: str, principal: str, audience: str,
                 boot_epoch: str, ttl: float = 60.0,
                 clock: Callable[[], float] = monotonic,
                 token_factory: Callable[[], str] | None = None) -> None:
        if (any(type(v) is not str or not v or len(v) > 128
                for v in (session, principal, audience, boot_epoch))
                or type(ttl) not in (int, float) or not math.isfinite(ttl)
                or not 0 < ttl <= 60):
            raise OfflineRefused()
        self._binding = (session, principal, audience, boot_epoch)
        self._ttl = ttl
        self._clock = clock
        self._tokens = token_factory
        self._lock = Lock()
        self._revision = 0
        self._challenge = None
        self._deadline = None
        self._last_time = float('-inf')
        self._attempted = False
        self._closed = False

    def __repr__(self) -> str:
        return "OfflineHandoffGate(<redacted>)"

    def _revoke(self) -> None:
        self._challenge = None
        self._deadline = None
        self._attempted = True

    def _now(self) -> float:
        try:
            now = self._clock()
            if (type(now) not in (int, float) or not math.isfinite(now)
                    or now < self._last_time):
                raise ValueError
        except Exception:
            self._revoke()
            raise OfflineRefused() from None
        self._last_time = now
        return now

    def event(self, kind: str) -> int:
        """Advance revision even for identical/restored values; discard closes."""
        with self._lock:
            if self._closed:
                raise OfflineRefused()
            if type(kind) is not str or kind not in (
                    'selection', 'action', 'source_reload', 'discard'):
                self._revoke()
                raise OfflineRefused()
            self._revision += 1
            if self._challenge is not None:
                self._revoke()
            if kind == 'discard':
                self._closed = True
                self._revoke()
                self._binding = None
            return self._revision

    def issue(self) -> OfflineChallenge:
        with self._lock:
            if self._closed or self._attempted or self._challenge is not None:
                self._revoke()
                raise OfflineRefused()
            now = self._now()
            try:
                token = self._tokens() if self._tokens else secrets.token_urlsafe(32)
                if type(token) is not str or not 16 <= len(token) <= 128:
                    raise ValueError
            except Exception:
                self._revoke()
                raise OfflineRefused() from None
            self._challenge = OfflineChallenge(token, self._revision)
            self._deadline = now + self._ttl
            return self._challenge

    def redeem(self, *, token: str, snapshot_revision: int, session: str,
               principal: str, audience: str, boot_epoch: str,
               confirmed: bool, rejected: bool = False) -> bool:
        """Consume before validation; ANY invalid attempt burns the challenge."""
        with self._lock:
            challenge, deadline = self._challenge, self._deadline
            self._revoke()
            now = self._now()
            fields = (session, principal, audience, boot_epoch)
            if (self._closed or challenge is None or deadline is None
                    or now >= deadline or confirmed is not True
                    or rejected is not False
                    or any(type(v) is not str for v in fields)
                    or fields != self._binding
                    or type(snapshot_revision) is not int
                    or snapshot_revision != challenge.revision
                    or snapshot_revision != self._revision
                    or type(token) is not str or token != challenge.token):
                raise OfflineRefused()
            return True

    def sweep(self) -> bool:
        """Explicit expiry purge; no scheduler exists in this offline model."""
        with self._lock:
            now = self._now()
            if self._deadline is not None and now >= self._deadline:
                self._revoke()
                return True
            return False

    def close(self) -> None:
        """Idempotently release retained references, without zeroization claims."""
        with self._lock:
            self._revoke()
            self._binding = None
            self._closed = True
