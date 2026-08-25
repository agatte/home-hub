"""
Philips Hue CLIP API v2 service — native scenes, dynamic effects, and the
server-sent EventStream that pushes external light changes (Hue app, wall
dimmer, motion sensor) to the dashboard in ~150ms instead of waiting for
the next v1 poll cycle.

Complements the v1 HueService (phue2) with direct HTTPS calls to the bridge's
CLIP v2 API. This enables native scene activation (visible to Alexa) and
dynamic light effects (candlelight, fireplace, sparkle, etc.).
"""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

import httpx

if TYPE_CHECKING:
    from backend.services.hue_service import HueService
    from backend.services.websocket_manager import WebSocketManager

logger = logging.getLogger("home_hub.hue_v2")

# EventStream reconnect backoff bounds. 1s initial avoids hammering a
# briefly-flapping bridge; 30s cap keeps the recovery window tight after
# a firmware reboot or ~24h SSE drop.
_STREAM_BACKOFF_INITIAL_SECONDS = 1.0
_STREAM_BACKOFF_MAX_SECONDS = 30.0

# Max gap between received SSE lines before we treat the connection as
# silently dead and force a reconnect. The Hue bridge normally emits
# `: hi` keepalives every ~10s; quiet periods of 200+s observed in prod
# (see digests/2026-05-17.md) indicate the TCP socket can go silent
# without httpx detecting a disconnect. Application-level liveness probe.
_STREAM_SILENT_RECONNECT_SECONDS = 90.0

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
        # Separate client for the EventStream. The REST client's base_url
        # points at /clip/v2/resource, but the SSE endpoint lives at
        # /eventstream/clip/v2 (one path level up). The stream client also
        # disables read timeout so a quiet stream isn't killed.
        self._stream_client: Optional[httpx.AsyncClient] = None
        self._connected = False
        # Maps v1 light IDs ("1", "2") to v2 UUIDs and vice versa
        self._v1_to_v2: dict[str, str] = {}
        self._v2_to_v1: dict[str, str] = {}
        # Scene cache (5-minute TTL)
        self._scene_cache: list[dict[str, Any]] = []
        self._scene_cache_time: float = 0
        self._scene_cache_ttl: float = 300  # 5 minutes
        # Heartbeat registry — injected via set_heartbeat_registry (same
        # pattern HueService uses). Ticked on every received stream frame
        # under the "hue_v2_stream" key so /health can surface silence.
        self._heartbeat = None

    @property
    def connected(self) -> bool:
        """Whether the v2 API connection is active."""
        return self._connected

    def set_heartbeat_registry(self, registry: Any) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    async def connect(self) -> None:
        """
        Initialize the HTTPS clients and build the v1↔v2 ID mapping.

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
            self._stream_client = httpx.AsyncClient(
                base_url=f"https://{self._bridge_ip}",
                headers={"hue-application-key": self._username},
                verify=False,
                # No read timeout — SSE connections are long-lived and the
                # bridge can go minutes between events.
                timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0),
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

        v1_to_v2: dict[str, str] = {}
        v2_to_v1: dict[str, str] = {}
        for light in data.get("data", []):
            v2_id = light.get("id", "")
            v1_ref = light.get("id_v1", "")
            if v1_ref.startswith("/lights/"):
                v1_id = v1_ref.split("/")[-1]
                v1_to_v2[v1_id] = v2_id
                v2_to_v1[v2_id] = v1_id
        # Bridge inventory can change between connects. Swap only a fully
        # rebuilt pair so removed fixtures cannot leave stale reverse entries.
        self._v1_to_v2 = v1_to_v2
        self._v2_to_v1 = v2_to_v1

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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # Hue bridge rate-limits aggressive bursts (~10 req/s); a
                # fan-out scene that hits set_effect_all on multiple lights
                # can clip into this. Transient — the next bridge poll
                # cycle reaches steady state. Not actionable, don't burn
                # Sentry events.
                logger.warning(
                    "Hue bridge rate-limited setting effect '%s' on light %s (429)",
                    effect, v1_light_id,
                )
                return False
            logger.error(
                f"Error setting effect '{effect}' on light {v1_light_id}: {e}"
            )
            return False
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
        return all(result is True for result in results)

    @property
    def mapped_light_ids(self) -> list[str]:
        """v1 light IDs affected by bridge-wide effect operations."""
        return list(self._v1_to_v2)

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
        """Close both HTTPS clients (REST + EventStream)."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._stream_client:
            await self._stream_client.aclose()
            self._stream_client = None
        self._connected = False

    # ------------------------------------------------------------------
    # EventStream — push-based external-change visibility (Phase 3)
    # ------------------------------------------------------------------

    async def event_stream_loop(
        self,
        ws_manager: "WebSocketManager",
        hue_v1_service: "HueService",
    ) -> None:
        """
        SSE consumer for the bridge's v2 EventStream.

        Pushes external light changes (Hue app slider, wall dimmer, motion
        sensor) to the dashboard via the existing `light_update` WebSocket
        broadcast, in ~150ms vs. the v1 polling floor of 0.5s.

        Scope: brightness + on/off only. v2 events deliver color as
        `color.xy` (CIE 1931) and we don't have a gamut-aware converter
        to v1's hue/sat (0-65535 / 0-254); color and CT changes fall
        through to the v1 polling fallback at 5s cadence.

        On a successful stream connection, signals HueService to demote
        its own polling to 5s (still acts as bridge-reachability heartbeat
        and color/ct catch-up); re-armed to tight cadence on disconnect.
        """
        if not self._stream_client:
            logger.warning("v2 event stream: no stream client, aborting")
            return

        backoff = _STREAM_BACKOFF_INITIAL_SECONDS

        while True:
            try:
                async with self._stream_client.stream(
                    "GET",
                    "/eventstream/clip/v2",
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    response.raise_for_status()
                    logger.info("v2 event stream connected")
                    backoff = _STREAM_BACKOFF_INITIAL_SECONDS

                    # The stream being up is sufficient to demote v1 polling to
                    # safety-net cadence — we don't wait for the first light
                    # event. On an idle bridge no `light` event ever arrives
                    # (only keepalives), which previously stranded v1 at 0.5s
                    # all night. v1's 5s poll still acts as the bridge-reach
                    # heartbeat and color/ct catch-up. Reset to False in the
                    # disconnect path below.
                    try:
                        hue_v1_service.set_v2_stream_active(True)
                    except AttributeError:
                        pass  # Older HueService without the flag; fail-soft.

                    line_iter = response.aiter_lines()
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                line_iter.__anext__(),
                                timeout=_STREAM_SILENT_RECONNECT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            # No bytes for the silence budget — bridge keepalives
                            # have stopped without httpx detecting a disconnect.
                            # Bail out so the outer loop reconnects and proves
                            # the socket is actually alive.
                            logger.warning(
                                "v2 event stream silent %.0fs — forcing reconnect",
                                _STREAM_SILENT_RECONNECT_SECONDS,
                            )
                            break
                        except StopAsyncIteration:
                            logger.info("v2 event stream ended, reconnecting")
                            break

                        # Any received line (including SSE keepalive comments)
                        # confirms the stream is alive. Ticking only on data:
                        # payloads went stale during quiet-bridge periods
                        # despite a healthy connection.
                        if self._heartbeat is not None:
                            self._heartbeat.tick("hue_v2_stream")
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if not payload:
                            continue

                        try:
                            events = json.loads(payload)
                        except json.JSONDecodeError:
                            logger.debug("v2 stream: malformed JSON payload")
                            continue

                        await self._dispatch_stream_events(
                            events, ws_manager, hue_v1_service
                        )

            except asyncio.CancelledError:
                logger.info("v2 event stream stopped (cancelled)")
                raise
            except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError) as e:
                logger.warning(
                    "v2 event stream closed (%s), backoff %.1fs",
                    type(e).__name__, backoff,
                )
            except Exception:
                logger.exception(
                    "v2 event stream unexpected error, backoff %.1fs", backoff
                )

            # Signal v1 polling to resume tight cadence while the stream
            # is down. Re-armed on the next successful connection above.
            try:
                hue_v1_service.set_v2_stream_active(False)
            except AttributeError:
                pass  # Older HueService without the flag; fail-soft.

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _STREAM_BACKOFF_MAX_SECONDS)

    async def _dispatch_stream_events(
        self,
        events: list,
        ws_manager: "WebSocketManager",
        hue_v1_service: "HueService",
    ) -> None:
        """
        Translate one v2 SSE batch into v1-shaped `light_update` broadcasts.

        Each batch is a JSON array; each object has a `type` and `data` list
        (Hue spec: top-level wraps a batch of resource updates). We walk the
        embedded `data` arrays and only act on `type=="light"` entries.
        """
        for envelope in events:
            for update in envelope.get("data", []):
                if update.get("type") != "light":
                    continue

                v2_id = update.get("id")
                if not v2_id:
                    continue
                v1_id = self._v2_to_v1.get(v2_id)
                if not v1_id:
                    logger.debug("v2 stream: no v1 mapping for %s", v2_id)
                    continue

                prev = hue_v1_service._last_states.get(v1_id)
                if prev is None:
                    # v1 polling hasn't filled the cache yet — let polling
                    # catch up; broadcasting a half-known dict would race.
                    logger.debug(
                        "v2 stream: skipping %s (v1 cache not populated yet)", v1_id
                    )
                    continue

                # Respect the inflight window — we just wrote this bulb,
                # the bridge event is mid-transition and would snap the UI
                # back to a stale value before the user releases the slider.
                now = time.monotonic()
                if now < hue_v1_service._inflight_until.get(v1_id, 0.0):
                    continue

                merged = dict(prev)
                changed = False

                on_field = update.get("on")
                if isinstance(on_field, dict) and "on" in on_field:
                    new_on = bool(on_field["on"])
                    if merged.get("on") != new_on:
                        merged["on"] = new_on
                        changed = True

                dimming = update.get("dimming")
                if isinstance(dimming, dict) and "brightness" in dimming:
                    # v2 brightness is 0-100 float. brightness==0 means the
                    # light is OFF; that state lives on the `on` field, don't
                    # write bri=0 (v1 range is 1-254).
                    brightness = dimming["brightness"]
                    if brightness and brightness > 0:
                        new_bri = max(1, min(254, int(round(brightness / 100 * 253 + 1))))
                        if merged.get("bri") != new_bri:
                            merged["bri"] = new_bri
                            changed = True

                if not changed:
                    continue

                # Update the v1 cache so the next poll diff doesn't
                # re-broadcast the same merged state we just pushed.
                hue_v1_service._last_states[v1_id] = merged
                await ws_manager.broadcast("light_update", merged)
