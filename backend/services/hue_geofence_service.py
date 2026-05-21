"""
Hue Bridge geofence service — event-driven away/home detection.

The Hue iOS app exposes a "Home & Away" automation that the user creates as
two ``behavior_instance`` resources: "Coming home" and "Leaving home." Each
fires when the user's phone crosses the geofence the app maintains via iOS
Core Location.

Polling ``/clip/v2/resource/geofence_client`` is a dead end on current bridge
firmware — Signify strips ``is_at_home`` from the third-party API for privacy
(verified empirically 2026-05-20). The bridge DOES emit SSE update events on
the behavior_instance resources when those automations fire, so this service
subscribes to ``HueV2Service``'s existing event dispatch and reacts to
events with matching IDs.

Wiring:
- ``HUE_GEOFENCE_HOME_BEHAVIOR_ID`` + ``HUE_GEOFENCE_AWAY_BEHAVIOR_ID`` env
  vars carry the UUIDs of the two behavior_instance resources. Discover via
  ``GET /clip/v2/resource/behavior_instance``, match by ``metadata.name``.
- Unset / empty IDs leave the service in idle/disconnected state — no event
  matching happens, ``is_home`` returns ``None``, ``connected`` stays False.

Caveat: We do not yet know whether the bridge emits behavior_instance update
events to third-party application keys on all firmware versions. If it
doesn't, ``_event_count`` stays zero across a walk-test and we'll need to
pivot to a different signal source.
"""
import logging
from typing import Any, Optional

logger = logging.getLogger("home_hub.hue_geofence")


class HueGeofenceService:
    """Event-driven away/home detector. Listens on the v2 SSE stream.

    Public surface matches the prior polling implementation (``connected``,
    ``is_home``, ``close``) so call sites don't need updating. The
    ``poll_loop`` method is gone — there is no polling.
    """

    def __init__(
        self,
        automation: Any,
        home_behavior_id: str,
        away_behavior_id: str,
    ) -> None:
        self._automation = automation
        self._home_behavior_id = (home_behavior_id or "").strip()
        self._away_behavior_id = (away_behavior_id or "").strip()
        self._is_home: Optional[bool] = None
        self._event_count: int = 0
        self._heartbeat = None

    @property
    def connected(self) -> bool:
        """True once at least one geofence event has been observed.

        Used by ``automation._is_away`` to decide whether to trust the
        ``is_home`` signal — a service with zero observed events can't
        reliably gate the autonomous setters.
        """
        return self._event_count > 0

    @property
    def is_home(self) -> Optional[bool]:
        """Last observed home/away state, or ``None`` before any event."""
        return self._is_home

    @property
    def configured(self) -> bool:
        """True when both behavior IDs are set — service is wired but may
        not yet have seen any events."""
        return bool(self._home_behavior_id and self._away_behavior_id)

    def set_heartbeat_registry(self, registry: Any) -> None:
        self._heartbeat = registry

    async def close(self) -> None:
        """No-op — there's no long-lived client to close in the SSE design.

        Kept for shutdown-sequence compatibility with the polling version.
        """
        return

    async def handle_event(self, update: dict, envelope_type: str) -> None:
        """Process one SSE event from ``HueV2Service``.

        Called by the v2 dispatcher for every ``behavior_instance`` event.
        We act only on ``"update"`` envelopes — bridge restarts emit
        ``"add"`` events for every existing behavior_instance, which would
        otherwise fire spurious away/home pushes at every restart.
        ``"delete"`` is also ignored.

        Match the event's ``id`` against the configured behavior IDs and
        drive automation overrides accordingly. Unknown IDs are ignored —
        the bridge emits behavior_instance events for the dimmer-switch
        automation, wake-up scheduler, etc., and we shouldn't react.
        """
        if not self.configured:
            return
        if envelope_type != "update":
            return

        event_id = update.get("id")
        if not event_id:
            return

        if event_id == self._away_behavior_id:
            await self._on_left()
        elif event_id == self._home_behavior_id:
            await self._on_arrived()
        else:
            return  # not one of ours

        if self._heartbeat is not None:
            self._heartbeat.tick("hue_geofence")

    async def _on_left(self) -> None:
        self._event_count += 1
        was_home = self._is_home
        self._is_home = False
        logger.info(
            "Hue geofence: 'Leaving home' fired (was_home=%s, event #%d) "
            "— pushing away mode",
            was_home, self._event_count,
        )
        try:
            await self._automation.set_manual_override(
                "away", source="hue_geofence",
            )
        except Exception as exc:
            logger.error(
                "hue_geofence away override failed: %s", exc, exc_info=True,
            )

    async def _on_arrived(self) -> None:
        self._event_count += 1
        was_home = self._is_home
        self._is_home = True
        logger.info(
            "Hue geofence: 'Coming home' fired (was_home=%s, event #%d) "
            "— clearing away override",
            was_home, self._event_count,
        )
        try:
            # Only clear if our away push is the active override. If the
            # user set something else (manual / Alexa / etc.) while away,
            # respect their choice.
            override_source = getattr(self._automation, "_override_source", None)
            override_mode = getattr(self._automation, "_override_mode", None)
            if override_source == "hue_geofence" or override_mode == "away":
                await self._automation.clear_override(source="hue_geofence")
            else:
                logger.info(
                    "hue_geofence: skipping clear — active override is "
                    "%s (source=%s), not ours",
                    override_mode, override_source,
                )
        except Exception as exc:
            logger.error(
                "hue_geofence clear_override failed: %s", exc, exc_info=True,
            )
