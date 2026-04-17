"""
Philips Hue bridge service — wraps phue2 for light control.
"""
import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("home_hub.hue")

# Extra buffer (seconds) added to a transition's own duration before the
# polling loop is allowed to broadcast again. Absorbs bridge processing lag.
INFLIGHT_BUFFER_SECONDS = 0.5

# Fallback assumed transition when the caller doesn't supply one. Matches
# phue2's default (4 deciseconds = 0.4s).
DEFAULT_TRANSITION_SECONDS = 0.4


class HueService:
    """
    Controls Philips Hue lights via the bridge's local API.

    Uses phue2 library for communication. Polls light state periodically
    and pushes changes to WebSocket clients.
    """

    def __init__(self, bridge_ip: str, username: str) -> None:
        self._bridge_ip = bridge_ip
        self._username = username
        self._bridge = None
        self._connected = False
        self._last_states: dict[str, dict] = {}
        # light_id -> monotonic deadline. While now() < deadline, the polling
        # loop skips that light so mid-transition bridge reads don't bounce
        # the UI back to stale values.
        self._inflight_until: dict[str, float] = {}

    @property
    def connected(self) -> bool:
        """Whether the bridge connection is active."""
        return self._connected

    async def connect(self) -> None:
        """
        Connect to the Hue bridge.

        On first-ever connection, the user must press the bridge's physical
        button. Subsequent connections use the stored username.
        """
        try:
            from phue import Bridge

            self._bridge = await asyncio.to_thread(
                Bridge, self._bridge_ip, self._username
            )
            self._connected = True
            logger.info(f"Connected to Hue bridge at {self._bridge_ip}")
        except ImportError:
            logger.error("phue2 not installed — run: pip install phue2")
            self._connected = False
        except Exception as e:
            logger.error(f"Failed to connect to Hue bridge: {e}")
            self._connected = False

    async def get_all_lights(self) -> list[dict]:
        """
        Get the state of all lights.

        Returns:
            List of light state dicts with id, name, on, bri, hue, sat.
        """
        if not self._connected or not self._bridge:
            return []

        try:
            api_data = await asyncio.to_thread(self._bridge.get_api)
            lights = []

            for light_id, light_data in api_data.get("lights", {}).items():
                state = light_data.get("state", {})
                lights.append({
                    "light_id": light_id,
                    "name": light_data.get("name", f"Light {light_id}"),
                    "on": state.get("on", False),
                    "bri": state.get("bri", 0),
                    "hue": state.get("hue", 0),
                    "sat": state.get("sat", 0),
                    "ct": state.get("ct"),
                    "colormode": state.get("colormode"),
                    "reachable": state.get("reachable", False),
                })

            return lights
        except Exception as e:
            logger.error(f"Error getting lights: {e}")
            return []

    async def get_light(self, light_id: str) -> Optional[dict]:
        """Get the state of a single light."""
        lights = await self.get_all_lights()
        for light in lights:
            if light["light_id"] == light_id:
                return light
        return None

    async def set_light(self, light_id: str, state: dict[str, Any]) -> bool:
        """
        Set the state of a single light.

        Args:
            light_id: The Hue bridge light ID.
            state: Dict with any of: on, bri, hue, sat, transitiontime.

        Returns:
            True if the command succeeded.
        """
        if not self._connected or not self._bridge:
            return False

        try:
            # phue2 expects int light IDs
            lid = int(light_id)

            # Build command dict — only include valid Hue API keys
            command: dict[str, Any] = {}
            if "on" in state:
                command["on"] = bool(state["on"])
            if "bri" in state:
                command["bri"] = max(1, min(254, int(state["bri"])))
            if "hue" in state:
                command["hue"] = max(0, min(65535, int(state["hue"])))
            if "sat" in state:
                command["sat"] = max(0, min(254, int(state["sat"])))
            if "ct" in state:
                command["ct"] = max(153, min(500, int(state["ct"])))
                # CT is exclusive of HSB on the Hue bridge. Force sat=0 and
                # drop any hue so the bulb cleanly uses CT. Without this,
                # residual hue/sat (either cached on the bridge from a prior
                # HSB mode, or re-introduced by the LightingPreferenceLearner
                # overlay) tints the "white," producing the greenish-bedroom
                # bug. This override always wins — any sat/hue the caller
                # passes alongside ct is dropped, matching Hue API semantics
                # where colormode is exclusive.
                command["sat"] = 0
                command.pop("hue", None)
            if "transitiontime" in state:
                command["transitiontime"] = int(state["transitiontime"])

            if not command:
                return False

            await asyncio.to_thread(
                self._bridge.set_light, lid, command
            )
            logger.info(f"Set light {light_id}: {command}")

            # Mark light in-flight so the polling loop doesn't broadcast
            # mid-transition bridge reads (which would bounce the UI back).
            if "transitiontime" in command:
                transition_seconds = command["transitiontime"] / 10.0
            else:
                transition_seconds = DEFAULT_TRANSITION_SECONDS
            self._inflight_until[light_id] = (
                time.monotonic() + transition_seconds + INFLIGHT_BUFFER_SECONDS
            )
            return True
        except Exception as e:
            logger.error(f"Error setting light {light_id}: {e}")
            return False

    async def set_all_lights(self, state: dict[str, Any]) -> bool:
        """Set the same state on all lights (used for scenes)."""
        lights = await self.get_all_lights()
        results = await asyncio.gather(
            *(self.set_light(light["light_id"], state) for light in lights)
        )
        return all(results)

    async def flash_lights(
        self,
        hue: int,
        sat: int,
        bri: int,
        duration: float,
        flash_count: int = 5,
    ) -> bool:
        """
        Flash all lights with a specific color for celebrations.

        Args:
            hue: Hue value (0-65535).
            sat: Saturation (0-254).
            bri: Brightness (0-254).
            duration: Total flash duration in seconds.
            flash_count: Number of on/off cycles.
        """
        if not self._connected:
            return False

        try:
            interval = duration / (flash_count * 2)

            for _ in range(flash_count):
                await self.set_all_lights({
                    "on": True, "bri": bri, "hue": hue, "sat": sat,
                    "transitiontime": 0,
                })
                await asyncio.sleep(interval)
                await self.set_all_lights({
                    "on": True, "bri": 1,
                    "transitiontime": 0,
                })
                await asyncio.sleep(interval)

            # Restore to a neutral state
            await self.set_all_lights({
                "on": True, "bri": 150, "hue": 8000, "sat": 140,
                "transitiontime": 10,
            })
            return True
        except Exception as e:
            logger.error(f"Error flashing lights: {e}")
            return False

    async def poll_state_loop(self, ws_manager) -> None:
        """
        Continuously poll light state and broadcast changes via WebSocket.

        Runs as a background task. Detects external changes (dimmer switch,
        Hue app) and pushes updates to all connected clients.
        """
        logger.info("Starting Hue state polling")

        while True:
            try:
                lights = await self.get_all_lights()
                now = time.monotonic()

                for light in lights:
                    lid = light["light_id"]

                    # Skip lights that were just written: their bridge state
                    # is mid-transition and would bounce the UI to a stale value.
                    if now < self._inflight_until.get(lid, 0.0):
                        continue

                    prev = self._last_states.get(lid)

                    if prev != light:
                        self._last_states[lid] = light
                        await ws_manager.broadcast("light_update", light)

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Hue polling stopped")
                break
            except Exception as e:
                logger.error(f"Hue polling error: {e}")
                await asyncio.sleep(5)
