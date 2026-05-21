"""
LAN presence detection — drives `away` mode from iPhone reachability.

Polls the Latitude's ARP neighbor table every ``poll_interval_seconds``
seconds looking for the configured iPhone IP. A UDP "nudge" packet is sent
to the phone before each poll to warm the kernel's ARP cache (iOS keeps
WiFi associated even when locked, but the router-side neighbor entry
expires after 60-300s of silence without traffic).

iOS 17/18 reliability hinges on "Settings → WiFi → (i) → Private WiFi
Address → Fixed" being set, which gives the iPhone a stable per-SSID MAC
the Latitude's ARP table can recognize across days. With "Rotating" the
phone presents a different MAC each session and ARP-table presence becomes
meaningless. Anthony has Fixed set per the network setup runbook.

State machine:
- ``MISS_THRESHOLD`` consecutive missed polls → push away override
- 1 hit (ARP REACHABLE/STALE) → clear away override

The asymmetric hysteresis is deliberate: returning home is unambiguous (a
device reappearing on the LAN is a real signal, no ambiguity), but
leaving needs debouncing against transient blips (router reassociation,
brief radio drop) that would otherwise spam mode flips.

Recommended cadence: 30s poll × 5 miss = ~2.5 min worst-case lag before
"left for the day" is committed. Single hit clears immediately on return.
"""
import asyncio
import logging
import socket
import subprocess
from typing import Any, Optional

logger = logging.getLogger("home_hub.lan_presence")

# Default cadence + miss threshold. Tunable via env (config.py).
DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_MISS_THRESHOLD = 5

# UDP probe target. Port 5353 (mDNS) is universally bound on iOS — even
# when locked the iPhone's networking stack responds to the kernel-level
# ARP request the OS sends to deliver the UDP packet, refreshing our
# neighbor entry. Payload is empty; we don't expect a reply.
_PROBE_PORT = 5353

# Subprocess timeout for `ip neigh show`. The command is local + sub-ms,
# so anything over 1s indicates a stuck shell — bail rather than block
# the poll loop.
_NEIGH_TIMEOUT_SECONDS = 2.0


class LanPresenceService:
    """Polls the ARP table to detect iPhone presence on the home LAN.

    Name deliberately distinguishes from the existing ``PresenceFusion``
    in ``presence_fusion.py`` (the multi-camera attendance / zone / posture
    aggregator) — both services touch "presence" but answer different
    questions. This one answers "is the phone on WiFi?"; that one answers
    "is the person physically here, and where in the room?".

    Surface mirrors the prior HueGeofenceService so call sites
    (``automation._lan_presence``, ``_is_away()``) just see an interface.
    """

    def __init__(
        self,
        automation: Any,
        phone_ip: str,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        miss_threshold: int = DEFAULT_MISS_THRESHOLD,
    ) -> None:
        self._automation = automation
        self._phone_ip = (phone_ip or "").strip()
        self._poll_interval = max(5, int(poll_interval_seconds))
        self._miss_threshold = max(1, int(miss_threshold))
        self._is_home: Optional[bool] = None
        self._consecutive_misses: int = 0
        self._poll_count: int = 0
        self._heartbeat = None

    @property
    def connected(self) -> bool:
        """True once at least one successful poll has produced a reading."""
        return self._poll_count > 0

    @property
    def is_home(self) -> Optional[bool]:
        """Last observed home/away state, or ``None`` before first poll."""
        return self._is_home

    @property
    def configured(self) -> bool:
        """True when ``PRESENCE_PHONE_IP`` is set. False = lane disabled,
        ``poll_loop`` exits immediately so the task isn't a no-op spin."""
        return bool(self._phone_ip)

    def set_heartbeat_registry(self, registry: Any) -> None:
        self._heartbeat = registry

    async def close(self) -> None:
        """No persistent resources — kept for shutdown-sequence symmetry."""
        return

    async def poll_loop(self) -> None:
        """Background poll loop. Runs forever until cancelled."""
        if not self.configured:
            logger.info(
                "Presence: idle (PRESENCE_PHONE_IP unset) — set it to "
                "enable LAN-based away detection"
            )
            return

        logger.info(
            "Presence poll loop started — ip=%s, interval=%ds, miss_threshold=%d",
            self._phone_ip, self._poll_interval, self._miss_threshold,
        )

        while True:
            try:
                # Both subprocess + socket calls are offloaded to the
                # default executor so a stuck `ip` shell (~2s timeout)
                # or a kernel-level UDP stall can't freeze the FastAPI
                # event loop. Fire-and-forget on the probe; await the
                # neighbor read since its result drives this iteration.
                await asyncio.to_thread(self._send_arp_probe)
                # Tiny wait lets the kernel actually do the ARP exchange
                # before we read the neighbor table. Without this, the
                # first poll after a long idle gap can see STALE/PROBE
                # state instead of the resolved REACHABLE.
                await asyncio.sleep(0.5)
                present = await asyncio.to_thread(self._is_phone_in_arp_table)
                self._poll_count += 1

                if present:
                    if self._is_home is False:
                        # Edge: away → home. Asymmetric — one hit clears.
                        await self._on_arrived()
                    self._is_home = True
                    self._consecutive_misses = 0
                else:
                    self._consecutive_misses += 1
                    if (
                        self._consecutive_misses >= self._miss_threshold
                        and self._is_home is not False
                    ):
                        # Edge: home (or unknown) → away. Threshold reached.
                        await self._on_left()
                        self._is_home = False

                if self._heartbeat is not None:
                    self._heartbeat.tick("lan_presence")

                await asyncio.sleep(self._poll_interval)

            except asyncio.CancelledError:
                logger.info("Presence poll loop cancelled")
                break
            except Exception:
                logger.exception("Presence poll error — continuing")
                await asyncio.sleep(self._poll_interval)

    def _send_arp_probe(self) -> None:
        """Send a zero-byte UDP packet at the phone's IP.

        Forces the kernel to ARP for the destination MAC if its neighbor
        entry has expired, refreshing the table for our subsequent read.
        Best-effort — silently swallow any error (network down, phone
        powered off, etc.).
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            try:
                sock.sendto(b"", (self._phone_ip, _PROBE_PORT))
            finally:
                sock.close()
        except Exception:
            pass

    def _is_phone_in_arp_table(self) -> bool:
        """Read the kernel neighbor table for the configured phone IP.

        ``ip neigh show <ip>`` returns one of:
        - empty (no entry exists yet — treat as absent)
        - ``<ip> dev wlan0 lladdr <mac> REACHABLE`` (present)
        - ``<ip> dev wlan0 lladdr <mac> STALE`` (present, cache aging)
        - ``<ip> dev wlan0  FAILED`` (probed, no response — absent)
        - ``<ip> dev wlan0  INCOMPLETE`` (probing — unknown, treat absent)

        Returns True only when the entry includes a resolved MAC. STALE
        counts as present because the device responded recently; it'll
        refresh to REACHABLE on the next packet exchange.
        """
        try:
            result = subprocess.run(
                ["ip", "neigh", "show", self._phone_ip],
                capture_output=True,
                text=True,
                timeout=_NEIGH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Presence: `ip neigh show` timed out")
            return False
        except FileNotFoundError:
            logger.error(
                "Presence: `ip` command not found — only Linux is supported"
            )
            return False
        except Exception:
            logger.exception("Presence: `ip neigh show` raised")
            return False

        line = (result.stdout or "").strip()
        if not line:
            return False
        if "FAILED" in line or "INCOMPLETE" in line:
            return False
        # Resolved entries always include "lladdr <mac>". Absent + transient
        # states (DELAY, PROBE on a never-resolved entry) don't.
        return "lladdr" in line

    async def _on_left(self) -> None:
        logger.info(
            "Presence: iPhone absent for %d consecutive polls (~%.1fs) "
            "— pushing away mode",
            self._consecutive_misses,
            self._consecutive_misses * self._poll_interval,
        )
        try:
            await self._automation.set_manual_override(
                "away", source="presence",
            )
        except Exception as exc:
            logger.error(
                "presence away override failed: %s", exc, exc_info=True,
            )

    async def _on_arrived(self) -> None:
        logger.info("Presence: iPhone back on LAN — clearing away override")
        try:
            override_source = getattr(
                self._automation, "_override_source", None,
            )
            override_mode = getattr(self._automation, "_override_mode", None)
            if override_source == "presence" or override_mode == "away":
                await self._automation.clear_override(source="presence")
            else:
                logger.info(
                    "Presence: skipping clear — active override is %s "
                    "(source=%s), not ours",
                    override_mode, override_source,
                )
        except Exception as exc:
            logger.error(
                "presence clear_override failed: %s", exc, exc_info=True,
            )
