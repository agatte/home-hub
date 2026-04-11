"""
Fauxmo Alexa integration — WeMo emulation for local voice control.

Exposes a fixed set of virtual Belkin WeMo switches on the LAN via UPnP.
Alexa discovers them natively ("Alexa, discover devices") and routes
on/off commands to our REST API via localhost httpx calls. Because the
commands flow through the same endpoints the dashboard uses, all the
usual event logging, WebSocket broadcasts, and mode-change callbacks
fire automatically — Alexa commands show up in event tables with
source/trigger='manual' for free.

We don't use fauxmo.main() because it creates its own asyncio loop.
Instead we mirror what main() does — create SSDPServer, instantiate our
custom plugins, and call loop.create_server() for each plugin — bound
to our running FastAPI loop.
"""
import asyncio
import hashlib
import logging
import socket
import struct
from typing import Any, Optional

import httpx
from fauxmo.fauxmo import Fauxmo, SSDPServer
from fauxmo.plugins import FauxmoPlugin

logger = logging.getLogger("home_hub.fauxmo")

SSDP_MCAST_GROUP = "239.255.255.250"
SSDP_PORT = 1900

# Port allocation — devices get deterministic ports in [FAUXMO_PORT_BASE,
# FAUXMO_PORT_BASE + FAUXMO_PORT_RANGE) derived from a hash of the device
# name. Stability across restarts matters because Alexa caches each
# discovered device's LOCATION (host:port); if the port changes on every
# uvicorn reload, previously-registered devices show up as "unresponsive"
# in the Alexa app until the user re-runs discovery.
FAUXMO_PORT_BASE = 52100
FAUXMO_PORT_RANGE = 5000


def _deterministic_port(name: str) -> int:
    """Map a device name to a stable port in the reserved range."""
    digest = hashlib.md5(name.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:4], "big") % FAUXMO_PORT_RANGE
    return FAUXMO_PORT_BASE + offset


def _make_ssdp_socket(iface_ip: str) -> socket.socket:
    """
    Build a UDP socket that listens for SSDP M-SEARCH probes on the given
    LAN interface.

    Fauxmo's built-in `make_udp_sock()` joins the multicast group using
    `INADDR_ANY`, which on Windows with multiple NICs (Wi-Fi + VPN + Docker +
    link-local) picks whichever interface the OS considers default. That's
    often not the real LAN interface, so Alexa's probes never reach the
    socket. Binding and joining on a specific interface IP fixes this.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    reuseport = getattr(socket, "SO_REUSEPORT", None)
    if reuseport:
        try:
            sock.setsockopt(socket.SOL_SOCKET, reuseport, 1)
        except OSError:
            pass
    sock.bind(("", SSDP_PORT))
    # Join the SSDP multicast group on the specified LAN interface (not INADDR_ANY)
    mreq = struct.pack(
        "4s4s",
        socket.inet_aton(SSDP_MCAST_GROUP),
        socket.inet_aton(iface_ip),
    )
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    # Also set the outbound multicast interface so responses go out the right NIC
    sock.setsockopt(
        socket.IPPROTO_IP,
        socket.IP_MULTICAST_IF,
        socket.inet_aton(iface_ip),
    )
    return sock

# Virtual devices Alexa will discover. Each entry: (name, on_req, off_req)
# where *_req is a tuple of (method, path, json_body_or_None).
DEVICE_MAP: list[dict[str, Any]] = [
    # "movie night", "arcade mode", etc. instead of "movie mode"/"gaming
    # mode" because Alexa reserves "movie", "gaming", and "cinema" for its
    # own built-in features (Echo sound modes, Fire TV profiles) and
    # silently drops WeMo devices whose names collide with those keywords.
    {
        "name": "movie night",
        "on": ("POST", "/api/automation/override", {"mode": "movie"}),
        "off": ("POST", "/api/automation/override", {"mode": "auto"}),
    },
    {
        "name": "relax mode",
        "on": ("POST", "/api/automation/override", {"mode": "relax"}),
        "off": ("POST", "/api/automation/override", {"mode": "auto"}),
    },
    {
        "name": "arcade mode",
        "on": ("POST", "/api/automation/override", {"mode": "gaming"}),
        "off": ("POST", "/api/automation/override", {"mode": "auto"}),
    },
    {
        "name": "party mode",
        "on": ("POST", "/api/automation/override", {"mode": "social"}),
        "off": ("POST", "/api/automation/override", {"mode": "auto"}),
    },
    {
        "name": "bedtime",
        "on": ("POST", "/api/automation/override", {"mode": "sleeping"}),
        "off": ("POST", "/api/automation/override", {"mode": "auto"}),
    },
    {
        "name": "music",
        "on": ("POST", "/api/sonos/play", None),
        "off": ("POST", "/api/sonos/pause", None),
    },
    {
        "name": "all lights",
        "on": ("POST", "/api/lights/all", {"on": True, "bri": 254}),
        "off": ("POST", "/api/lights/all", {"on": False}),
    },
]


class HomeHubFauxmoPlugin(FauxmoPlugin):
    """
    Fauxmo plugin that dispatches on/off to a localhost REST endpoint.

    Fire-and-forget: the sync on()/off() methods schedule the HTTP call on
    the running event loop and return True immediately. Alexa doesn't wait
    on the API round-trip beyond the TCP ACK fauxmo itself sends.
    """

    def __init__(
        self,
        *,
        name: str,
        port: int,
        on_req: tuple[str, str, Optional[dict]],
        off_req: tuple[str, str, Optional[dict]],
        client: httpx.AsyncClient,
    ) -> None:
        # initial_state="off" seeds _latest_action so get_state() has something
        # to return when Alexa queries GetBinaryState during discovery. Without
        # it, the base class's latest_action property raises AttributeError and
        # the SOAP response is never sent, causing Alexa to timeout and reject
        # the device.
        super().__init__(name=name, port=port, initial_state="off")
        self._on_req = on_req
        self._off_req = off_req
        self._client = client

    async def _dispatch(self, req: tuple[str, str, Optional[dict]]) -> None:
        method, path, body = req
        try:
            resp = await self._client.request(method, path, json=body)
            if resp.status_code >= 400:
                logger.warning(
                    "Fauxmo '%s' -> %s %s returned %d: %s",
                    self._name, method, path, resp.status_code, resp.text[:200],
                )
            else:
                logger.info("Fauxmo '%s' -> %s %s OK", self._name, method, path)
        except Exception as e:
            logger.error(
                "Fauxmo '%s' -> %s %s failed: %s (%s)",
                self._name, method, path, e, type(e).__name__,
            )

    def _schedule(self, req: tuple[str, str, Optional[dict]]) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("Fauxmo plugin called outside a running loop")
            return False
        loop.create_task(self._dispatch(req))
        return True

    def on(self) -> bool:
        return self._schedule(self._on_req)

    def off(self) -> bool:
        return self._schedule(self._off_req)

    def get_state(self) -> str:
        # Fauxmo has no reliable way to reflect current dashboard state
        # back to Alexa, so fall back on the latest-action helper that the
        # base class maintains via its __getattribute__ interceptor.
        return super().get_state()


class FauxmoService:
    """
    Manages SSDP + per-device HTTP servers for Alexa discovery.

    Lifecycle:
        fauxmo = FauxmoService(local_ip="192.168.1.30", enabled=True)
        await fauxmo.start()   # binds sockets, registers devices
        # ... server runs ...
        await fauxmo.stop()    # tears down sockets, closes httpx client
    """

    def __init__(
        self,
        local_ip: str,
        api_port: int = 8000,
        enabled: bool = False,
    ) -> None:
        self._local_ip = local_ip
        self._api_port = api_port
        self._enabled = enabled
        self._connected = False
        self._ssdp_server: Optional[SSDPServer] = None
        self._ssdp_transport: Optional[asyncio.DatagramTransport] = None
        self._servers: list[tuple[FauxmoPlugin, asyncio.AbstractServer]] = []
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        """Bind SSDP multicast socket and spin up per-device HTTP servers."""
        if not self._enabled:
            logger.info("Fauxmo disabled (FAUXMO_ENABLED=false)")
            return

        # Attach the home_hub log handlers to the fauxmo namespace so
        # fauxmo's warnings/errors land in the same file. Level stays at
        # WARNING — full DEBUG floods the log with every SSDP probe and
        # is only useful for active discovery debugging.
        fauxmo_logger = logging.getLogger("fauxmo")
        fauxmo_logger.setLevel(logging.WARNING)
        home_hub_logger = logging.getLogger("home_hub")
        for h in home_hub_logger.handlers:
            if h not in fauxmo_logger.handlers:
                fauxmo_logger.addHandler(h)
        fauxmo_logger.propagate = False

        loop = asyncio.get_running_loop()

        # Shared httpx client pointed at our own FastAPI server
        base_url = f"http://127.0.0.1:{self._api_port}"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=5.0,
            headers={"User-Agent": "HomeHub-Fauxmo/1.0"},
        )

        # Build plugins with deterministic ports so Alexa's cached device
        # URLs stay valid across backend restarts.
        plugins: list[HomeHubFauxmoPlugin] = []
        used_ports: set[int] = set()
        for device in DEVICE_MAP:
            port = _deterministic_port(device["name"])
            # Defensive: if two names happen to hash to the same port,
            # linearly probe forward until we find a free slot.
            while port in used_ports:
                port += 1
            used_ports.add(port)
            plugin = HomeHubFauxmoPlugin(
                name=device["name"],
                port=port,
                on_req=device["on"],
                off_req=device["off"],
                client=self._client,
            )
            plugins.append(plugin)

        # SSDP multicast listener (UDP 1900) bound explicitly to our LAN interface
        try:
            self._ssdp_server = SSDPServer()
            sock = _make_ssdp_socket(self._local_ip)
            transport, _ = await loop.create_datagram_endpoint(
                lambda: self._ssdp_server, sock=sock
            )
            self._ssdp_transport = transport
            logger.info(
                "Fauxmo SSDP listening on %s:%d (multicast group %s)",
                self._local_ip, SSDP_PORT, SSDP_MCAST_GROUP,
            )
        except Exception as e:
            logger.error("Fauxmo SSDP bind failed: %s", e, exc_info=True)
            await self._cleanup_client()
            return

        # Per-device HTTP servers
        for plugin in plugins:
            try:
                factory = lambda p=plugin: Fauxmo(name=p.name, plugin=p)
                server = await loop.create_server(
                    factory, host=self._local_ip, port=plugin.port
                )
                self._servers.append((plugin, server))
                self._ssdp_server.add_device(plugin.name, self._local_ip, plugin.port)
                logger.info(
                    "Fauxmo device registered: '%s' on %s:%d",
                    plugin.name, self._local_ip, plugin.port,
                )
            except Exception as e:
                logger.error(
                    "Fauxmo device '%s' failed to bind on port %d: %s",
                    plugin.name, plugin.port, e,
                )

        self._connected = True
        logger.info(
            "Fauxmo started on %s — %d virtual devices registered",
            self._local_ip, len(self._servers),
        )

    async def stop(self) -> None:
        """Tear down all servers and close the shared httpx client."""
        if not self._connected:
            return

        # Close per-device TCP servers
        for plugin, server in self._servers:
            try:
                plugin.close()
            except Exception as e:
                logger.debug("Plugin close error for '%s': %s", plugin.name, e)
            server.close()
            try:
                await server.wait_closed()
            except Exception as e:
                logger.debug("Server wait_closed error: %s", e)
        self._servers.clear()

        # Close SSDP datagram endpoint
        if self._ssdp_transport is not None:
            try:
                self._ssdp_transport.close()
            except Exception as e:
                logger.debug("SSDP transport close error: %s", e)
            self._ssdp_transport = None
        self._ssdp_server = None

        await self._cleanup_client()
        self._connected = False
        logger.info("Fauxmo stopped")

    async def _cleanup_client(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.debug("httpx close error: %s", e)
            self._client = None
