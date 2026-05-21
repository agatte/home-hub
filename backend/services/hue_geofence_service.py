"""
Hue Bridge geofence service — surfaces phone-based home/away from the bridge.

The Hue iOS app already maintains a geofence per linked phone; the bridge
exposes that state at ``/clip/v2/resource/geofence_client``. This service
polls the endpoint on a 60s cadence and, on transitions, drives the
``automation_engine`` into / out of the ``away`` mode:

- home → away (no clients home): ``set_manual_override("away", source="hue_geofence")``
- away → home (any client home):  ``clear_override(source="hue_geofence")``

Fail-soft on first contact. If the bridge returns zero ``geofence_client``
resources (the user hasn't enabled geofencing in the Hue iOS app), the
service logs once and stays disabled — the ``connected`` flag stays False
and downstream code (``automation._is_away``) treats every tick as
"signal unavailable / assume home".

Hue geofence lag is 5–15 min in practice, dictated by iOS's location-fix
cadence and how aggressively the Hue app re-checks. That's fine for the
"user left for the day" use case; short trips don't need to trip away.
"""
import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.hue_geofence")

POLL_INTERVAL_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 10.0


class HueGeofenceService:
    """Polls the Hue Bridge geofence_client resource and drives away mode."""

    def __init__(self, bridge_ip: str, username: str, automation: Any) -> None:
        self._bridge_ip = bridge_ip
        self._username = username
        self._automation = automation
        self._base_url = f"https://{bridge_ip}/clip/v2/resource"
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._is_home: Optional[bool] = None
        self._heartbeat = None

    @property
    def connected(self) -> bool:
        """True once a successful poll has produced a home/away reading."""
        return self._connected

    @property
    def is_home(self) -> Optional[bool]:
        """Most recent aggregated geofence reading; None until first poll succeeds."""
        return self._is_home

    def set_heartbeat_registry(self, registry: Any) -> None:
        self._heartbeat = registry

    async def connect(self) -> None:
        """Open the HTTPS client and confirm the bridge exposes geofence_clients.

        Leaves ``_connected`` False if the user hasn't enabled Hue geofencing —
        the service will keep polling so a later iOS setup flips it on without
        a restart.
        """
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"hue-application-key": self._username},
            verify=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        try:
            initial = await self._fetch_is_home()
        except Exception as exc:
            logger.warning("Hue geofence initial fetch failed: %s", exc)
            return
        if initial is None:
            logger.info(
                "Hue geofence: bridge has no geofence_client resources — "
                "enable geofencing in the Hue iOS app to activate away mode"
            )
            return
        self._is_home = initial
        self._connected = True
        logger.info(
            "Hue geofence connected — initial state: %s",
            "home" if initial else "AWAY",
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def poll_loop(self) -> None:
        """Background loop — drives away/home transitions every 60s."""
        logger.info("Hue geofence poll loop started")
        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("hue_geofence")
                # Allow a delayed setup — if the user just enabled geofencing
                # in the iOS app, the next poll succeeds and flips _connected.
                is_home = await self._fetch_is_home()
                if is_home is None:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                previous = self._is_home
                self._is_home = is_home
                self._connected = True

                if previous is None:
                    # First successful read. If we already booted in the AWAY
                    # state (user left during a deploy / power-cycle) and no
                    # other override is active, push away now so lights catch
                    # up. Restored overrides from app_settings take priority —
                    # _on_left() is a no-op when an override is already set.
                    logger.info(
                        "Hue geofence first read: %s",
                        "home" if is_home else "AWAY",
                    )
                    if not is_home and not getattr(
                        self._automation, "_manual_override", False,
                    ):
                        await self._on_left()
                elif previous and not is_home:
                    await self._on_left()
                elif not previous and is_home:
                    await self._on_arrived()

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                logger.info("Hue geofence poll loop cancelled")
                break
            except Exception as exc:
                logger.error("Hue geofence poll error: %s", exc, exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _fetch_is_home(self) -> Optional[bool]:
        """Aggregate is_at_home across every geofence_client on the bridge.

        Returns:
            True  — at least one client is currently at home
            False — every client is away
            None  — no clients are defined (geofencing not enabled in app)
        """
        if self._client is None:
            return None
        resp = await self._client.get("/geofence_client")
        resp.raise_for_status()
        data = resp.json()
        clients = data.get("data", []) or []
        if not clients:
            return None
        # Bridge CLIP v2 has used `is_at_home` historically; tolerate a
        # rename to `at_home` without forcing a redeploy.
        flags: list[bool] = []
        for client in clients:
            if "is_at_home" in client:
                flags.append(bool(client["is_at_home"]))
            elif "at_home" in client:
                flags.append(bool(client["at_home"]))
        if not flags:
            logger.warning(
                "Hue geofence: %d clients found but none expose is_at_home/"
                "at_home — schema may have changed, treating as home",
                len(clients),
            )
            return True
        return any(flags)

    async def _on_left(self) -> None:
        logger.info("Hue geofence: home → AWAY, pushing away mode")
        try:
            await self._automation.set_manual_override(
                "away", source="hue_geofence",
            )
        except Exception as exc:
            logger.error("hue_geofence away override failed: %s", exc, exc_info=True)

    async def _on_arrived(self) -> None:
        logger.info("Hue geofence: AWAY → home, clearing away override")
        try:
            # Only clear if the active override is our away push. If the
            # user manually set something else while we were "away" (e.g.
            # via Alexa, dashboard, or the override survived a deploy),
            # respect that — only undo our own state.
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
