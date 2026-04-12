"""
Philips Hue CLIP API v2 service — native scenes and dynamic effects.

Complements the v1 HueService (phue2) with direct HTTPS calls to the bridge's
CLIP v2 API. This enables native scene activation (visible to Alexa) and
dynamic light effects (candlelight, fireplace, sparkle, etc.).
"""
import asyncio
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.hue_v2")

# Dynamic effects supported by Hue v2 API
AVAILABLE_EFFECTS = [
    {"name": "candle", "display_name": "Candlelight", "description": "Warm flickering candle effect"},
    {"name": "fire", "display_name": "Fireplace", "description": "Shifting oranges and reds"},
    {"name": "sparkle", "display_name": "Sparkle", "description": "Random bright flashes"},
    {"name": "prism", "display_name": "Prism", "description": "Slow color cycling"},
    {"name": "glisten", "display_name": "Glisten", "description": "Gentle shimmering glow"},
    {"name": "opal", "display_name": "Opal", "description": "Soft pastel transitions"},
]


class HueV2Service:
    """
    Controls Philips Hue lights via the CLIP API v2.

    Uses direct HTTPS calls to the bridge for features not available in phue2:
    native scene management, dynamic effects, and room groupings.
    """

    def __init__(self, bridge_ip: str, username: str) -> None:
        self._bridge_ip = bridge_ip
        self._username = username
        self._base_url = f"https://{bridge_ip}/clip/v2/resource"
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        # Maps v1 light IDs ("1", "2") to v2 UUIDs and vice versa
        self._v1_to_v2: dict[str, str] = {}
        self._v2_to_v1: dict[str, str] = {}
        # Scene cache (5-minute TTL)
        self._scene_cache: list[dict[str, Any]] = []
        self._scene_cache_time: float = 0
        self._scene_cache_ttl: float = 300  # 5 minutes

    @property
    def connected(self) -> bool:
        """Whether the v2 API connection is active."""
        return self._connected

    async def connect(self) -> None:
        """
        Initialize the HTTPS client and build the v1↔v2 ID mapping.

        The bridge uses a self-signed certificate, so SSL verification is
        disabled. The v1 API username works as the v2 API key.
        """
        try:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"hue-application-key": self._username},
                verify=False,
                timeout=10.0,
            )
            # Test connectivity and build ID map
            await self._build_id_map()
            self._connected = True
            logger.info(
                f"Hue v2 API connected — {len(self._v1_to_v2)} lights mapped"
            )
        except Exception as e:
            logger.error(f"Failed to connect to Hue v2 API: {e}")
            self._connected = False

    async def _build_id_map(self) -> None:
        """Build mapping between v1 integer IDs and v2 UUIDs."""
        resp = await self._client.get("/light")
        resp.raise_for_status()
        data = resp.json()

        for light in data.get("data", []):
            v2_id = light.get("id", "")
            v1_ref = light.get("id_v1", "")
            if v1_ref.startswith("/lights/"):
                v1_id = v1_ref.split("/")[-1]
                self._v1_to_v2[v1_id] = v2_id
                self._v2_to_v1[v2_id] = v1_id

    def v1_to_v2_id(self, v1_id: str) -> Optional[str]:
        """Convert a v1 light ID to its v2 UUID."""
        return self._v1_to_v2.get(v1_id)

    def v2_to_v1_id(self, v2_id: str) -> Optional[str]:
        """Convert a v2 UUID to its v1 light ID."""
        return self._v2_to_v1.get(v2_id)

    # ------------------------------------------------------------------
    # Scenes
    # ------------------------------------------------------------------

    async def get_scenes(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """
        List all native scenes stored on the Hue bridge (5-min cache).

        These scenes are visible to Alexa and the Hue app.

        Args:
            force_refresh: Bypass cache and fetch from bridge.

        Returns:
            List of scene dicts with id, name, group, and status.
        """
        if not self._connected or not self._client:
            return []

        # Return cached if fresh
        if (
            not force_refresh
            and self._scene_cache
            and (time.monotonic() - self._scene_cache_time) < self._scene_cache_ttl
        ):
            return self._scene_cache

        try:
            resp = await self._client.get("/scene")
            resp.raise_for_status()
            data = resp.json()

            scenes = []
            for scene in data.get("data", []):
                group_ref = scene.get("group", {}).get("rid", "")
                scenes.append({
                    "id": scene.get("id", ""),
                    "name": scene.get("metadata", {}).get("name", "Unknown"),
                    "group_id": group_ref,
                    "status": scene.get("status", {}).get("active", "inactive"),
                    "source": "bridge",
                })

            scenes.sort(key=lambda s: s["name"])
            self._scene_cache = scenes
            self._scene_cache_time = time.monotonic()
            return scenes
        except Exception as e:
            logger.error(f"Error fetching v2 scenes: {e}")
            return self._scene_cache if self._scene_cache else []

    async def activate_scene(self, scene_id: str) -> bool:
        """
        Activate a native Hue scene by its v2 UUID.

        Args:
            scene_id: The v2 scene UUID.

        Returns:
            True if activation succeeded.
        """
        if not self._connected or not self._client:
            return False

        try:
            resp = await self._client.put(
                f"/scene/{scene_id}",
                json={"recall": {"action": "active"}},
            )
            resp.raise_for_status()
            logger.info(f"Activated native scene: {scene_id}")
            return True
        except Exception as e:
            logger.error(f"Error activating scene {scene_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # Dynamic effects
    # ------------------------------------------------------------------

    async def set_effect(self, v1_light_id: str, effect: str) -> bool:
        """
        Apply a dynamic effect to a single light.

        Args:
            v1_light_id: The v1 integer light ID (e.g., "1").
            effect: Effect name — one of: candle, fire, sparkle, prism,
                    glisten, opal.

        Returns:
            True if the effect was applied.
        """
        if not self._connected or not self._client:
            return False

        v2_id = self.v1_to_v2_id(v1_light_id)
        if not v2_id:
            logger.error(f"No v2 ID found for v1 light {v1_light_id}")
            return False

        try:
            resp = await self._client.put(
                f"/light/{v2_id}",
                json={"effects": {"effect": effect}},
            )
            resp.raise_for_status()
            logger.info(f"Set effect '{effect}' on light {v1_light_id}")
            return True
        except Exception as e:
            logger.error(
                f"Error setting effect '{effect}' on light {v1_light_id}: {e}"
            )
            return False

    async def set_effect_all(self, effect: str) -> bool:
        """Apply a dynamic effect to all mapped lights (parallel)."""
        if not self._v1_to_v2:
            return False

        results = await asyncio.gather(
            *(self.set_effect(v1_id, effect) for v1_id in self._v1_to_v2)
        )
        return any(results)

    async def stop_effect(self, v1_light_id: str) -> bool:
        """Stop any active effect on a light."""
        return await self.set_effect(v1_light_id, "no_effect")

    async def stop_effect_all(self) -> bool:
        """Stop effects on all lights."""
        return await self.set_effect_all("no_effect")

    async def get_effects(self) -> list[dict[str, str]]:
        """Return the list of available dynamic effects."""
        return AVAILABLE_EFFECTS.copy()

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    async def get_rooms(self) -> list[dict[str, Any]]:
        """
        List rooms configured on the Hue bridge.

        Returns:
            List of room dicts with id, name, and light IDs.
        """
        if not self._connected or not self._client:
            return []

        try:
            resp = await self._client.get("/room")
            resp.raise_for_status()
            data = resp.json()

            rooms = []
            for room in data.get("data", []):
                children = room.get("children", [])
                light_ids = [
                    c.get("rid", "")
                    for c in children
                    if c.get("rtype") == "device"
                ]
                rooms.append({
                    "id": room.get("id", ""),
                    "name": room.get("metadata", {}).get("name", "Unknown"),
                    "light_ids": light_ids,
                })

            return rooms
        except Exception as e:
            logger.error(f"Error fetching rooms: {e}")
            return []

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the HTTPS client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False
