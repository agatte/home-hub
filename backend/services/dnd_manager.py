"""
Do Not Disturb state machine — extracted from AutomationEngine
(GH#86 step 2 of the decomposition).

Owns the enabled/expiry/duration state, persistence to
``app_settings["dnd_state"]``, and the ``dnd_update`` WS broadcast.
AutomationEngine keeps thin delegating methods (``is_dnd_active``,
``dnd_status``, ``enable_dnd``, ``clear_dnd``, ``load_dnd_state``) so
external callers (routes, remediation, bootstrap, notifier gating) are
untouched.

The WS manager is read through a getter because the engine receives it
after construction; reading at broadcast time mirrors the original
``self._ws_manager`` late-binding behavior.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from backend.services.automation_constants import DND_STATE_KEY, TZ

# Same logger name as the engine so journald output (and every grep recipe
# built on it) is unchanged by the extraction.
logger = logging.getLogger("home_hub.automation")


class DndManager:
    """DND window state + persistence + broadcast.

    Pure state machine — contains no gating policy. Callers (engine
    run_loop, report_activity, set/clear override, NotifierService,
    CelebrationOrchestrator) decide what DND suppresses; this class only
    answers "is it active?" and manages the window lifecycle.
    """

    def __init__(self, ws_manager_getter: Callable[[], Any]) -> None:
        self._ws_manager_getter = ws_manager_getter
        self._enabled: bool = False
        self._expiry: Optional[datetime] = None
        self._duration_minutes: int = 0

    def is_active(self) -> bool:
        """True iff DND is enabled and the expiry is still in the future.

        Pure check — no side effects. Expiry actuation (broadcast +
        persist) happens once per tick in the engine ``run_loop`` so
        callers can invoke this freely from gating paths.
        """
        if not self._enabled:
            return False
        if self._expiry is None:
            return False
        return datetime.now(tz=TZ) < self._expiry

    def should_expire(self, now: datetime) -> bool:
        """True iff DND is enabled but ``now`` has reached the expiry.

        The engine run_loop calls this once per tick and fires the lazy
        clear (persist + WS broadcast) — keeps ``is_active`` side-effect
        free while the dashboard learns about expiry within ~60s.
        """
        return self._enabled and self._expiry is not None and now >= self._expiry

    def status(self) -> dict:
        """Return DND state as a JSON-serializable dict for API responses."""
        active = self.is_active()
        if not active or self._expiry is None:
            return {
                "enabled": False,
                "expiry_utc": None,
                "minutes_remaining": 0,
                "duration_minutes": 0,
            }
        remaining = (self._expiry - datetime.now(tz=TZ)).total_seconds()
        return {
            "enabled": True,
            "expiry_utc": self._expiry.astimezone(timezone.utc).isoformat(),
            "minutes_remaining": max(0, int(remaining // 60)),
            "duration_minutes": self._duration_minutes,
        }

    async def enable(
        self, duration_minutes: int = 120, source: str = "internal",
    ) -> dict:
        """Activate DND for ``duration_minutes`` (clamped to [1, 720])."""
        clamped = max(1, min(720, int(duration_minutes)))
        now = datetime.now(tz=TZ)
        self._enabled = True
        self._expiry = now + timedelta(minutes=clamped)
        self._duration_minutes = clamped
        logger.info(
            "DND enabled: %d minutes (expiry=%s, source=%s)",
            clamped, self._expiry.isoformat(), source,
        )
        await self._persist()
        await self._broadcast()
        return self.status()

    async def clear(self, source: str = "internal") -> dict:
        """Clear DND immediately."""
        was_enabled = self._enabled
        self._enabled = False
        self._expiry = None
        self._duration_minutes = 0
        if was_enabled:
            logger.info("DND cleared (source=%s)", source)
        await self._persist()
        await self._broadcast()
        return self.status()

    async def load_state(self) -> None:
        """Restore DND state from app_settings on startup.

        If the persisted expiry has passed, treat as cleared and persist
        the cleared state so the dashboard renders correctly on first load.
        """
        from backend.api.routes.routines import load_setting

        try:
            saved = await load_setting(DND_STATE_KEY)
        except Exception as e:
            logger.error("Failed to load DND state: %s", e, exc_info=True)
            return
        if not saved or not saved.get("enabled"):
            return
        expiry_str = saved.get("expiry_utc")
        if not expiry_str:
            return
        try:
            expiry = datetime.fromisoformat(expiry_str).astimezone(TZ)
        except (TypeError, ValueError):
            logger.warning("Invalid DND expiry on load: %r", expiry_str)
            return
        if expiry <= datetime.now(tz=TZ):
            logger.info(
                "DND expiry (%s) had passed on startup — treating as cleared",
                expiry.isoformat(),
            )
            await self.clear(source="startup_expired")
            return
        self._enabled = True
        self._expiry = expiry
        self._duration_minutes = int(saved.get("duration_minutes", 0))
        logger.info(
            "DND restored from app_settings: expiry=%s (%d min remaining)",
            expiry.isoformat(),
            int((expiry - datetime.now(tz=TZ)).total_seconds() // 60),
        )

    async def _persist(self) -> None:
        """Write current DND state to app_settings."""
        from backend.api.routes.routines import save_setting

        if self._enabled and self._expiry is not None:
            payload = {
                "enabled": True,
                "expiry_utc": self._expiry.astimezone(timezone.utc).isoformat(),
                "duration_minutes": self._duration_minutes,
            }
        else:
            payload = {
                "enabled": False,
                "expiry_utc": None,
                "duration_minutes": 0,
            }
        try:
            await save_setting(DND_STATE_KEY, payload)
        except Exception as e:
            logger.error("Failed to persist DND state: %s", e, exc_info=True)

    async def _broadcast(self) -> None:
        """Broadcast DND state change to all WebSocket clients."""
        ws_manager = self._ws_manager_getter()
        if not ws_manager:
            return
        try:
            await ws_manager.broadcast("dnd_update", self.status())
        except Exception as e:
            logger.error("Failed to broadcast DND state: %s", e, exc_info=True)
