"""Thread-safe authority gate for the desktop YAMNet classifier.

The activity detector submits evidence to Latitude; Latitude remains the
semantic authority.  This gate changes desired classifier state only from a
successful server response (or a read-only authoritative status snapshot),
never from a local process candidate alone.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class ClassifierGate:
    """Shared desired/actual state for the ambient classifier lifecycle."""

    def __init__(self, configured: bool) -> None:
        self._lock = threading.Lock()
        self._configured = configured
        self._desired_enabled = configured
        self._actual_enabled = False
        self._reason = "startup" if configured else "not_configured"
        self._detail = "awaiting ambient monitor"
        self._authoritative_mode: str | None = None
        self._reported_mode: str | None = None
        self._semantic_disposition: str | None = None
        self._updated_at = time.time()

    def desired_enabled(self) -> bool:
        with self._lock:
            return self._desired_enabled

    def update_from_activity(self, reported_mode: str, result: dict[str, Any]) -> bool:
        """Apply one successful Latitude activity decision.

        Missing authority is treated as non-actionable: keep the current gate
        rather than trusting a local candidate that the backend may reject.
        """
        authoritative = result.get("authoritative_mode")
        if not self._configured or not isinstance(authoritative, str):
            return False
        disposition = result.get("semantic_disposition")
        reason = str(result.get("reason") or "activity_report")
        desired = authoritative != "gaming"
        with self._lock:
            changed = desired != self._desired_enabled
            self._desired_enabled = desired
            self._reason = reason
            self._authoritative_mode = authoritative
            self._reported_mode = reported_mode
            self._semantic_disposition = (
                str(disposition) if disposition is not None else None
            )
            self._updated_at = time.time()
        return changed

    def update_from_status(self, status: dict[str, Any]) -> bool:
        """Prime desired state from an authoritative automation status read."""
        if not self._configured:
            return False
        authoritative = status.get("current_mode")
        if not isinstance(authoritative, str):
            return False
        desired = authoritative != "gaming"
        with self._lock:
            changed = desired != self._desired_enabled
            self._desired_enabled = desired
            self._reason = "startup_status"
            self._authoritative_mode = authoritative
            self._reported_mode = None
            self._semantic_disposition = None
            self._updated_at = time.time()
        return changed

    def set_actual(self, enabled: bool, detail: str) -> None:
        with self._lock:
            self._actual_enabled = enabled
            self._detail = detail
            self._updated_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": self._configured,
                "desired_enabled": self._desired_enabled,
                "actual_enabled": self._actual_enabled,
                "reason": self._reason,
                "detail": self._detail,
                "authoritative_mode": self._authoritative_mode,
                "reported_mode": self._reported_mode,
                "semantic_disposition": self._semantic_disposition,
                "updated_at": self._updated_at,
            }
