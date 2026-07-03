"""
Decision-pipeline broadcaster — ring buffer + throttle + WS emit,
extracted from AutomationEngine (GH#86 step 3 of the decomposition).

Deliberately narrow (critic #2): ONLY the snapshot ring, the 1s
broadcast throttle, and the ``pipeline_state`` WS emit live here.
Building the snapshot (``_build_pipeline_state``) and the mode
broadcast (``_broadcast_mode``) stay on the engine — they read live
engine state and belong with it.

The WS manager and the state builder are read through callables because
the engine assigns its WS manager after construction; evaluating at
broadcast time mirrors the original late-binding behavior.
"""
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from backend.services.automation_constants import TZ

# Same logger name as the engine so journald output is unchanged.
logger = logging.getLogger("home_hub.automation")

# Snapshots kept for the /api/automation/pipeline history view.
RING_SIZE = 30
# Minimum seconds between WS broadcasts — callers can invoke freely
# (mode changes + the periodic run_loop tick) without flooding clients.
MIN_BROADCAST_INTERVAL_SECONDS = 1.0


class PipelineBroadcaster:
    """Throttled pipeline_state WS broadcast with a bounded history ring."""

    def __init__(
        self,
        ws_manager_getter: Callable[[], Any],
        state_builder: Callable[[], dict],
    ) -> None:
        self._ws_manager_getter = ws_manager_getter
        self._build_state = state_builder
        self._history: list[dict] = []
        self._last_broadcast: Optional[datetime] = None

    @property
    def history(self) -> list[dict]:
        """Snapshot ring, oldest first (bounded at RING_SIZE)."""
        return self._history

    async def broadcast(self) -> None:
        """Build a snapshot, append to the ring, and emit (throttled)."""
        now = datetime.now(tz=TZ)
        if (
            self._last_broadcast
            and (now - self._last_broadcast).total_seconds()
            < MIN_BROADCAST_INTERVAL_SECONDS
        ):
            return
        self._last_broadcast = now

        state = self._build_state()
        self._history.append(state)
        if len(self._history) > RING_SIZE:
            self._history.pop(0)

        await self._ws_manager_getter().broadcast("pipeline_state", state)
