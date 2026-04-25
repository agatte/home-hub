"""
Async circuit breaker for wrapping calls into flaky external services.

Used by HueService and SonosService to keep a slow / unresponsive bridge
from wedging the polling loop. State machine:

    closed --(N consecutive failures)--> open
    open   --(cooldown elapsed)-------->  half_open
    half_open --(success)-------------->  closed
    half_open --(failure)-------------->  open  (cooldown restarts)

A per-call timeout via ``asyncio.wait_for`` bounds how long any single
call can block before being counted as a failure. The underlying thread
(when wrapping ``asyncio.to_thread``) keeps running until the sync code
returns — phue/SoCo eventually time out at the request layer (~10s) so
the leak is transient.

Exposed via ``snapshot()`` for ``/health``; pairs with the heartbeat
surface to distinguish "calls failing" from "loop wedged".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """Raised by ``CircuitBreaker.call`` when the breaker is open and
    the cooldown hasn't elapsed yet. Callers (poll loops) typically
    catch and log; route handlers should propagate as HTTP 503."""

    def __init__(self, name: str) -> None:
        super().__init__(f"circuit breaker '{name}' is open")
        self.name = name


class CircuitBreaker:
    """Per-service async breaker. Thread-safe state mutations under a
    short-held Lock so the synchronous ``snapshot()`` and ``state``
    helpers can be read from any thread (e.g. /health request handler)
    without coordinating with the event loop."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        call_timeout: float = 5.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")
        if call_timeout <= 0:
            raise ValueError("call_timeout must be > 0")

        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.call_timeout = call_timeout

        self._state = self.CLOSED
        self._consecutive_failures = 0
        self._opened_at: Optional[datetime] = None
        self._last_success_at: Optional[datetime] = None
        self._lock = Lock()

    # ---- state helpers --------------------------------------------------

    @property
    def state(self) -> str:
        """Current state, accounting for cooldown elapsed since open.

        Reads only — does NOT promote open to half_open. The promotion
        happens inside ``call()`` so the half-open probe is atomic with
        the call attempt that earns it.
        """
        with self._lock:
            if self._state == self.OPEN and self._cooldown_elapsed_locked():
                return self.HALF_OPEN
            return self._state

    def _cooldown_elapsed_locked(self) -> bool:
        if self._opened_at is None:
            return True
        age = (datetime.now(timezone.utc) - self._opened_at).total_seconds()
        return age >= self.cooldown_seconds

    def snapshot(self) -> dict[str, Any]:
        """Return current breaker state for /health. Thread-safe."""
        with self._lock:
            state = self._state
            if state == self.OPEN and self._cooldown_elapsed_locked():
                state = self.HALF_OPEN
            return {
                "state": state,
                "consecutive_failures": self._consecutive_failures,
                "opened_at": self._opened_at.isoformat() if self._opened_at else None,
                "last_success_at": (
                    self._last_success_at.isoformat()
                    if self._last_success_at
                    else None
                ),
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
            }

    # ---- mutation -------------------------------------------------------

    def _record_success_locked(self) -> None:
        if self._state in (self.OPEN, self.HALF_OPEN):
            logger.info("Circuit breaker '%s' closing after success", self.name)
        self._state = self.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._last_success_at = datetime.now(timezone.utc)

    def _record_failure_locked(self) -> None:
        self._consecutive_failures += 1
        if self._state == self.HALF_OPEN:
            # Probe failed — open with fresh cooldown.
            logger.warning(
                "Circuit breaker '%s' re-opening after half-open failure", self.name
            )
            self._state = self.OPEN
            self._opened_at = datetime.now(timezone.utc)
            return
        if self._consecutive_failures >= self.failure_threshold:
            if self._state != self.OPEN:
                logger.warning(
                    "Circuit breaker '%s' opening after %d consecutive failures",
                    self.name, self._consecutive_failures,
                )
                self._state = self.OPEN
                self._opened_at = datetime.now(timezone.utc)

    # ---- call -----------------------------------------------------------

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run ``fn(*args, **kwargs)`` (which must return an awaitable)
        under the breaker.

        Wrapped value semantics:
        - When state is ``open`` and cooldown hasn't elapsed: raise
          ``CircuitBreakerOpen`` without invoking ``fn``.
        - When state is ``open`` and cooldown HAS elapsed: promote to
          half_open and run the call as a probe.
        - On success: record and return the result.
        - On any exception (including ``asyncio.TimeoutError`` from the
          per-call timeout): record as failure and re-raise.
        """
        # Promotion + gate, atomic under the lock.
        with self._lock:
            if self._state == self.OPEN:
                if not self._cooldown_elapsed_locked():
                    raise CircuitBreakerOpen(self.name)
                # Cooldown elapsed — flip to half_open and let the call run.
                logger.info("Circuit breaker '%s' probing (half-open)", self.name)
                self._state = self.HALF_OPEN

        try:
            awaitable = fn(*args, **kwargs)
            result = await asyncio.wait_for(awaitable, timeout=self.call_timeout)
        except BaseException:
            with self._lock:
                self._record_failure_locked()
            raise
        else:
            with self._lock:
                self._record_success_locked()
            return result
