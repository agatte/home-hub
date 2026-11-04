"""Explicitly injected, in-memory ACK observation; no application wiring or IO.

Only sanitized summaries survive a call. Inputs must be stable built-in JSON
trees, as required by hue_ack_summary. No physical completion is inferred.
"""
import math
import time
from threading import Lock

from backend.services.hue_ack_summary import summarize_v1, summarize_v2


class OneShotHueAckObserver:
    """Capture at most two envelopes within 60 seconds of construction.

    A trusted test clock may replace monotonic. Expiry is checked on access;
    no timer or background worker is created. Contended observations abstain.
    """

    def __init__(self, max_events=1, ttl_seconds=60, *, clock=time.monotonic):
        if type(max_events) is not int or not 1 <= max_events <= 2:
            raise ValueError("invalid observation limit")
        if (type(ttl_seconds) not in (int, float)
                or not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 60):
            raise ValueError("invalid observation lifetime")
        self._clock = clock
        self._deadline = clock() + ttl_seconds
        self._max_events = max_events
        self._events = []
        self._armed = True
        self._lock = Lock()

    def _active(self):
        if self._clock() >= self._deadline:
            self._armed = False
        return self._armed and len(self._events) < self._max_events

    def _observe(self, summarize, *args):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._active():
                summary = summarize(*args)
                # Also check expiry after bounded sanitization.
                if self._active():
                    self._events.append(summary)
                    if len(self._events) == self._max_events:
                        self._armed = False
        except Exception:
            self._armed = False  # No raw input or exception retention.
        finally:
            self._lock.release()

    def observe_v1(self, result, command, light_id):
        self._observe(summarize_v1, result, command, light_id)

    def observe_v2(self, status, result, expected_id, expected_type):
        self._observe(summarize_v2, status, result, expected_id, expected_type)

    def disarm(self):
        with self._lock:
            self._armed = False

    def get_summaries(self):
        """Return independent copies, without timestamps or identifiers."""
        with self._lock:
            try:
                self._active()
            except Exception:
                self._armed = False
            return [{key: list(value) if type(value) is list else value
                     for key, value in event.items()} for event in self._events]
