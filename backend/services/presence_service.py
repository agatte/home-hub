"""
Presence detection service — monitors iPhone on WiFi to detect home/away.

Two independent signals:

1. **iPhone Shortcut webhook (primary).** iOS Personal Automations fire
   POST /api/automation/presence/{arrived,departed} on WiFi
   connect/disconnect. Those route into `on_shortcut_arrival` /
   `on_shortcut_departure` — instant, no network probing, bypasses
   debounce.

2. **Active ARP probe (backup).** Every ``probe_interval`` seconds the
   loop runs ``arping -c 1`` against the phone's IP. ARP queries the L2
   binding directly, which is far more reliable than ICMP ping on iOS —
   the phone keeps its AP association alive even when it's ignoring
   pings in battery-saver. Catches cases where the Shortcut didn't fire
   (iOS killed background tasks, phone rebooted, etc.).

ICMP ping was removed 2026-04-19 after it produced ten phantom `away`
events in one stay-home day on prod.

Phase 2 (planned): BLE proximity detection for "at the door" precision.
"""
import asyncio
import logging
import platform
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Optional

from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Indiana/Indianapolis")

logger = logging.getLogger("home_hub.presence")

# Light wave order: kitchen door → kitchen back → living room → bedroom
ARRIVAL_WAVE_ORDER = ["3", "4", "1", "2"]

# Time-of-day arrival light states (warm welcoming brightness per period)
ARRIVAL_LIGHT_STATES: dict[str, dict[str, Any]] = {
    "morning": {"on": True, "bri": 200, "ct": 300},     # Bright warm
    "afternoon": {"on": True, "bri": 220, "ct": 250},   # Neutral bright
    "evening": {"on": True, "bri": 160, "ct": 370},     # Warm golden
    "night": {"on": True, "bri": 40, "ct": 454},        # Very dim warm
}

# Time-of-day → Hue effect after arrival
ARRIVAL_EFFECTS: dict[str, Optional[str]] = {
    "morning": None,
    "afternoon": "opal",
    "evening": "opal",
    "night": "candle",
}

# Weather overrides for effects
WEATHER_EFFECT_OVERRIDES: dict[str, str] = {
    "thunderstorm": "sparkle",
    "rain": "candle",
    "snow": "candle",
}

# Time-of-day → music mode for MusicMapper
ARRIVAL_MUSIC_MODES: dict[str, Optional[str]] = {
    "morning": "working",
    "afternoon": "working",
    "evening": "relax",
    "night": None,
}

# iOS WiFi-flap filters. The Shortcut "Disconnected from [home SSID]"
# automation fires on *any* drop — including brief power-save cycles and
# handoffs where the phone never physically leaves the apartment. Without
# filters, each flap triggers a full welcome-home ceremony.
#
# Layer 1 — departure debounce: when /departed arrives, delay the fade
# sequence by this many seconds. If /arrived fires before the timer
# elapses, the pending departure is cancelled and presence state never
# leaves "home" — invisible flap.
DEPARTURE_DEBOUNCE_SECONDS = 45
# Layer 2 — flap gate on arrival: if the actual disconnect duration
# (back-dated to `_last_seen` when ARP triggered the departure, or set
# at Shortcut-receive time for the /departed path) is under the
# threshold, suppress the ceremony. Two thresholds so we can trust
# explicit Shortcut signals more than ARP-only detection:
# - FLAP_THRESHOLD_MINUTES_SHORTCUT (2 min): when /arrived fires, iOS
#   had an explicit connect event, so the disconnect was real from
#   iOS's perspective. Filter only rapid flaps.
# - FLAP_THRESHOLD_MINUTES_ARP (5 min): when arrival came via ARP
#   2-probe debounce with no Shortcut, be conservative because ARP
#   can miss the phone during deep iOS power-save for 3–5 min stretches
#   even while the user is home.
FLAP_THRESHOLD_MINUTES_SHORTCUT = 2
FLAP_THRESHOLD_MINUTES_ARP = 5


@dataclass
class PresenceConfig:
    """Persisted presence detection configuration."""

    enabled: bool = True
    phone_ip: str = "192.168.1.148"
    phone_mac: str = "A2:DD:D9:65:EE:F8"
    probe_interval: int = 20              # Seconds between ARP probes
    away_timeout: int = 180               # 3 min — active ARP is reliable
    short_absence_threshold: int = 1800   # 30 min — skip ceremony
    arrival_volume: int = 25
    departure_fade_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceConfig":
        """Create config from a dict, ignoring unknown keys."""
        data = dict(data)
        # Back-compat: legacy `ping_interval` key from before the ARP switch
        if "ping_interval" in data and "probe_interval" not in data:
            data["probe_interval"] = data.pop("ping_interval")
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class PresenceService:
    """
    WiFi-based phone presence detection with arrival/departure sequences.

    Runs as a background task in the FastAPI lifespan. Every
    ``probe_interval`` seconds it runs an active ARP probe against the
    configured phone IP. Arrival/departure can also be signalled directly
    via ``on_shortcut_arrival`` / ``on_shortcut_departure`` from an iPhone
    Personal Automation webhook, which is the preferred path — it fires
    immediately and bypasses the ARP debounce.

    Transitions:

    - **home → away**: After ``away_timeout`` seconds with no ARP hit
      (and no Shortcut keepalive), runs a gradual departure sequence.
    - **away → home (ARP path)**: Requires 2 consecutive successful
      probes to fire the arrival sequence. Absorbs transient ARP misses
      and prevents phantom arrivals from brief WiFi stutter.
    - **away → home (Shortcut path)**: Fires immediately on webhook.
    - **departing → home**: Immediate cancel + arrival (mid-fade; no
      debounce — the phone is clearly still here).
    - **unknown → home/away**: On startup, sets state without triggering
      sequences (prevents false arrival on server restart).
    """

    def __init__(
        self,
        hue,
        hue_v2,
        sonos,
        tts,
        weather_service,
        automation_engine,
        music_mapper,
        ws_manager,
        event_logger=None,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        self._hue = hue
        self._hue_v2 = hue_v2
        self._sonos = sonos
        self._tts = tts
        self._weather_service = weather_service
        self._automation = automation_engine
        self._music_mapper = music_mapper
        self._ws_manager = ws_manager
        self._event_logger = event_logger

        self._config = PresenceConfig.from_dict(config or {})
        self._state: str = "unknown"
        self._last_seen: Optional[datetime] = None
        self._away_since: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._pending_arrival_confirms: int = 0
        self._departure_task: Optional[asyncio.Task] = None
        self._arrival_task: Optional[asyncio.Task] = None
        # Shortcut /departed debounce. Holds a pending task that will call
        # _on_departure after DEPARTURE_DEBOUNCE_SECONDS unless cancelled
        # by a subsequent /arrived firing first (the iOS WiFi flap pattern).
        self._pending_departure_task: Optional[asyncio.Task] = None

        self._is_linux = platform.system() == "Linux"
        self._probe_iface: Optional[str] = None   # Detected at first probe

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def config(self) -> PresenceConfig:
        """Current configuration."""
        return self._config

    def config_dict(self) -> dict[str, Any]:
        """Config as a JSON-serializable dict."""
        return asdict(self._config)

    def get_status(self) -> dict[str, Any]:
        """Current presence state for REST / MCP / WebSocket."""
        now = datetime.now(tz=TZ)
        # Map internal states to public-facing values
        public_state = (
            "away" if self._state in ("startup_away",) else self._state
        )
        away_duration = None
        if self._away_since and self._state in (
            "away", "departing", "startup_away"
        ):
            away_duration = int((now - self._away_since).total_seconds() / 60)

        return {
            "state": public_state,
            "enabled": self._config.enabled,
            "phone_ip": self._config.phone_ip,
            "last_seen": (
                self._last_seen.isoformat() if self._last_seen else None
            ),
            "away_since": (
                self._away_since.isoformat() if self._away_since else None
            ),
            "away_duration_minutes": away_duration,
        }

    async def update_config(self, new_config: dict[str, Any]) -> None:
        """Hot-reload configuration from API."""
        self._config = PresenceConfig.from_dict(
            {**asdict(self._config), **new_config}
        )
        logger.info("Presence config updated: %s", new_config)

    async def on_shortcut_arrival(self, source: str = "ios_shortcut") -> str:
        """
        Explicit arrival signal from an iPhone Personal Automation (or
        similar external source). Fires the welcome-home ceremony
        immediately, bypassing the ARP debounce.

        Returns a short status token: ``"fired"`` if the ceremony was
        triggered, ``"noop"`` if the state was already home/arriving,
        ``"flap_cancelled"`` if a pending-departure task was cancelled
        (iOS WiFi flap), or ``"silent"`` if the signal landed during
        startup.
        """
        # Single consistent prefix per webhook hit so journalctl can show
        # raw webhook rate independent of what the backend decides below.
        logger.info(
            "presence.shortcut.arrived source=%s pre_state=%s pending_departure=%s",
            source,
            self._state,
            bool(
                self._pending_departure_task
                and not self._pending_departure_task.done()
            ),
        )
        now = datetime.now(tz=TZ)
        self._consecutive_failures = 0
        self._pending_arrival_confirms = 0
        self._last_seen = now

        # Short-circuit the iOS WiFi flap pattern: if a /departed is pending
        # debounce (no fade has started yet), cancel it silently. State
        # stayed "home" the whole time — no ceremony, no fade, no user-
        # visible twitch. This is the dominant fix path for the reported
        # multiple-ceremony bug.
        if (
            self._pending_departure_task
            and not self._pending_departure_task.done()
        ):
            self._pending_departure_task.cancel()
            self._pending_departure_task = None
            # Flap never committed to departing, so the pre-set _away_since
            # must be cleared — otherwise a later genuine trip would be
            # back-dated to the flap's disconnect time.
            self._away_since = None
            logger.info(
                "Shortcut arrival (%s) — cancelled pending departure "
                "(iOS WiFi flap within %ds debounce)",
                source, DEPARTURE_DEBOUNCE_SECONDS,
            )
            return "flap_cancelled"

        if self._state in ("home", "arriving"):
            logger.info(
                "Shortcut arrival (%s) — already %s, skipping ceremony",
                source, self._state,
            )
            return "noop"

        if self._state in ("unknown", "startup_away"):
            # Backend just started; signal is the first ground truth.
            # User has been home — no ceremony.
            self._state = "home"
            logger.info(
                "Shortcut arrival (%s) on startup — state set to home",
                source,
            )
            await self._broadcast_state()
            return "silent"

        # away / departing → full ceremony. force_ceremony=True bypasses
        # the short_absence_threshold skip — a Shortcut firing means the
        # phone physically left WiFi range and returned, which is explicit
        # "went out and came back" evidence and always deserves the
        # welcome-home sequence regardless of how long they were gone.
        logger.info("Shortcut arrival (%s) — firing ceremony", source)
        await self._on_arrival(force_ceremony=True)
        return "fired"

    async def on_shortcut_departure(self, source: str = "ios_shortcut") -> str:
        """
        Explicit departure signal from an iPhone Personal Automation.

        Does NOT start the fade sequence immediately — schedules it for
        ``DEPARTURE_DEBOUNCE_SECONDS`` from now. If a subsequent
        ``on_shortcut_arrival`` lands before the timer elapses, the
        pending task is cancelled silently (iOS WiFi flap). Only real
        departures (disconnect held > debounce window) fire the fade.

        Bypasses the manual-override guard when it does commit — a WiFi
        disconnect held past the flap window is strong enough evidence
        of actual departure to override any active mode.

        Returns ``"pending"`` if the debounced task was scheduled,
        ``"noop"`` if state is already away/departing or a pending task
        already exists.
        """
        logger.info(
            "presence.shortcut.departed source=%s pre_state=%s pending_departure=%s",
            source,
            self._state,
            bool(
                self._pending_departure_task
                and not self._pending_departure_task.done()
            ),
        )
        if self._state in ("away", "departing", "startup_away"):
            logger.info(
                "Shortcut departure (%s) — already %s, skipping",
                source, self._state,
            )
            return "noop"

        if (
            self._pending_departure_task
            and not self._pending_departure_task.done()
        ):
            logger.info(
                "Shortcut departure (%s) — already debounced, waiting",
                source,
            )
            return "noop"

        logger.info(
            "Shortcut departure (%s) — pending for %ds",
            source, DEPARTURE_DEBOUNCE_SECONDS,
        )
        # Capture the actual disconnect moment now. If the deferred task
        # commits (real trip), duration_away on the arrival side measures
        # from here instead of the commit time 45s later — otherwise real
        # sub-minute absences read as 0-minute and get flap-gated away.
        # Cleared by on_shortcut_arrival when it cancels the pending task.
        if self._away_since is None:
            self._away_since = datetime.now(tz=TZ)
        self._pending_departure_task = asyncio.create_task(
            self._deferred_departure(source)
        )
        return "pending"

    async def _deferred_departure(self, source: str) -> None:
        """Wait out the debounce window, then commit the departure.

        Cancelled silently by ``on_shortcut_arrival`` when the phone
        reconnects within the window (iOS WiFi flap).
        """
        try:
            await asyncio.sleep(DEPARTURE_DEBOUNCE_SECONDS)
            logger.info(
                "Shortcut departure (%s) — committing after %ds debounce",
                source, DEPARTURE_DEBOUNCE_SECONDS,
            )
            await self._on_departure(skip_override_guard=True, trigger="shortcut")
        except asyncio.CancelledError:
            logger.debug("Deferred departure cancelled (flap)")
            raise
        finally:
            self._pending_departure_task = None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Background task — ARP probe every interval, manage state."""
        logger.info(
            "Presence detection started (phone=%s, interval=%ds, away_timeout=%ds)",
            self._config.phone_ip,
            self._config.probe_interval,
            self._config.away_timeout,
        )

        while True:
            try:
                if not self._config.enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)
                reachable = await self._arp_probe(self._config.phone_ip)

                if reachable:
                    self._consecutive_failures = 0
                    self._last_seen = now

                    if self._state in ("unknown", "startup_away"):
                        # Startup — set home without triggering arrival.
                        # Clear _away_since so the public status doesn't
                        # show a stale disconnect timestamp that was set
                        # by the startup-away branch.
                        self._state = "home"
                        self._pending_arrival_confirms = 0
                        self._away_since = None
                        logger.info("Initial presence: home")
                    elif self._state == "departing":
                        # Mid-fade and phone came back — cancel immediately.
                        # No debounce: state hasn't committed to away yet,
                        # and the user is clearly still here.
                        self._pending_arrival_confirms = 0
                        await self._on_arrival()
                    elif self._state == "away":
                        # Committed-away → require 2 consecutive probes
                        # before firing the ceremony. Protects against
                        # transient ARP misses and brief WiFi stutter.
                        self._pending_arrival_confirms += 1
                        if self._pending_arrival_confirms >= 2:
                            self._pending_arrival_confirms = 0
                            await self._on_arrival()
                        else:
                            logger.info(
                                "Arrival probe %d/2 — waiting for confirmation",
                                self._pending_arrival_confirms,
                            )

                else:
                    self._consecutive_failures += 1
                    self._pending_arrival_confirms = 0

                    # Opportunistic MAC → IP re-binding after 3 misses
                    # (covers DHCP-assigned new IP while we were away)
                    if (
                        self._consecutive_failures == 3
                        and self._is_linux
                    ):
                        new_ip = await self._arp_lookup(
                            self._config.phone_mac
                        )
                        if new_ip and new_ip != self._config.phone_ip:
                            logger.info(
                                "Phone IP changed: %s → %s",
                                self._config.phone_ip,
                                new_ip,
                            )
                            self._config.phone_ip = new_ip
                            continue  # Retry immediately with new IP

                    if self._state == "unknown":
                        # First failure on startup — use interim state
                        # so a successful probe next cycle sets "home"
                        # instead of triggering a false arrival
                        self._state = "startup_away"
                        self._away_since = now
                        logger.info("Initial presence: away (startup)")
                    elif (
                        self._state == "startup_away"
                        and self._last_seen is None
                        and (now - self._away_since).total_seconds()
                        >= self._config.away_timeout
                    ):
                        # Never seen the phone and timeout elapsed —
                        # user is genuinely away
                        self._state = "away"
                        logger.info("Startup away confirmed — phone not seen")
                    elif (
                        self._state == "home"
                        and self._last_seen
                        and (now - self._last_seen).total_seconds()
                        >= self._config.away_timeout
                    ):
                        await self._on_departure()

                await self._broadcast_state()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Presence loop error: %s", e, exc_info=True)

            await asyncio.sleep(self._config.probe_interval)

    # ------------------------------------------------------------------
    # ARP probe (active L2 detection) + cache lookup (IP re-binding)
    # ------------------------------------------------------------------

    async def _arp_probe(self, ip: str) -> bool:
        """
        Active ARP probe via `arping -c 1 -w 2`. Returns True if the
        phone's L2 address is on the network.

        Prefer this over ICMP ping — iOS gates ICMP aggressively when
        the phone is locked / in WiFi power-save, producing frequent
        false "away" events. The L2 association survives power-save,
        so ARP is the reliable signal.

        On non-Linux platforms falls back to ICMP ping (dev machines).
        """
        if not self._is_linux:
            return await self._icmp_ping(ip)

        iface = await self._detect_interface(ip)
        cmd = ["arping", "-c", "1", "-w", "2"]
        if iface:
            cmd.extend(["-I", iface])
        cmd.append(ip)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=4.0)
            return proc.returncode == 0
        except FileNotFoundError:
            # arping not installed — fall back to ICMP once and log loudly
            logger.warning(
                "arping not found — install iputils-arping for reliable "
                "presence detection. Falling back to ICMP ping."
            )
            self._is_linux = False  # Skip the arping path for the rest of the session
            return await self._icmp_ping(ip)
        except (asyncio.TimeoutError, OSError) as e:
            logger.debug("ARP probe failed for %s: %s", ip, e)
            return False

    async def _icmp_ping(self, ip: str) -> bool:
        """
        ICMP fallback — used only on non-Linux (dev machines) or when
        `arping` isn't installed on the host.
        """
        try:
            if platform.system() == "Linux":
                cmd = ["ping", "-c", "1", "-W", "2", ip]
            else:
                cmd = ["ping", "-n", "1", "-w", "2000", ip]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return proc.returncode == 0
        except (asyncio.TimeoutError, OSError) as e:
            logger.debug("ICMP ping failed for %s: %s", ip, e)
            return False

    async def _detect_interface(self, ip: str) -> Optional[str]:
        """
        Resolve the outbound interface for ``ip`` once and cache it.
        ``arping -I`` needs an explicit interface; picking the one the
        kernel would actually use avoids probing the wrong NIC.
        """
        if self._probe_iface:
            return self._probe_iface
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip", "-o", "route", "get", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            # Format: "192.168.1.148 dev wlp2s0 src 192.168.1.210 uid 1000"
            parts = stdout.decode().split()
            if "dev" in parts:
                self._probe_iface = parts[parts.index("dev") + 1]
                logger.info("Presence probe interface: %s", self._probe_iface)
        except (asyncio.TimeoutError, OSError, ValueError):
            # Let arping pick its own default — not fatal
            pass
        return self._probe_iface

    async def _arp_lookup(self, mac: str) -> Optional[str]:
        """Check ARP table for a MAC address, return its IP if found."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip", "neigh", "show",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
            # Normalize target MAC to lowercase
            target = mac.lower().replace("-", ":")

            for line in stdout.decode().splitlines():
                parts = line.split()
                # Format: "192.168.1.148 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
                if len(parts) >= 5 and parts[3] == "lladdr":
                    if parts[4].lower() == target:
                        return parts[0]
            return None
        except (asyncio.TimeoutError, OSError) as e:
            logger.debug("ARP lookup failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Departure
    # ------------------------------------------------------------------

    async def _on_departure(
        self,
        *,
        skip_override_guard: bool = False,
        trigger: str = "arp_timeout",
    ) -> None:
        """
        Start the departure sequence as a background task.

        ``skip_override_guard`` lets the Shortcut webhook bypass the
        manual-override check below — an iPhone "disconnected from
        home WiFi" event is explicit evidence of leaving, stronger than
        any active mode.

        ``trigger`` tags which signal fired the departure so activity
        events can be grouped after the fact: ``"shortcut"`` for an
        iPhone WiFi-disconnect webhook, ``"arp_timeout"`` for an ARP
        probe miss held past ``away_timeout``. ARP is the default
        because it's the only path that calls this without passing
        explicit context.
        """
        # Skip departure if a manual override is active. An explicit mode
        # (relax, social, cooking, watching, sleeping, etc.) is strong
        # presence evidence — a long ARP silence during live use is
        # almost always phone-side (charger + DND, weak signal, iOS network
        # throttling) rather than an actual departure. Reset the countdown
        # so the next real miss is evaluated freshly after the override
        # clears.
        if (
            not skip_override_guard
            and self._automation
            and self._automation.manual_override
        ):
            logger.info(
                "Presence: phone unreachable for %ds but manual override "
                "is active (%s) — skipping departure, resetting countdown",
                self._config.away_timeout,
                self._automation.override_mode,
            )
            self._last_seen = datetime.now(tz=TZ)
            self._consecutive_failures = 0
            return

        if self._arrival_task and not self._arrival_task.done():
            self._arrival_task.cancel()
            self._arrival_task = None

        self._state = "departing"
        # Back-date _away_since to when the phone actually became
        # unreachable (not when we decided to declare away). For ARP-
        # triggered aways, `_last_seen` holds the final successful
        # probe — a real trip will show its true length on the arrival
        # side. For Shortcut-triggered aways, `on_shortcut_departure`
        # pre-sets _away_since at Shortcut-receive time; don't overwrite.
        if self._away_since is None:
            self._away_since = self._last_seen or datetime.now(tz=TZ)
        logger.info(
            "Departure detected (trigger=%s) — starting fade sequence", trigger
        )
        self._departure_task = asyncio.create_task(
            self._departure_sequence(trigger=trigger)
        )

    async def _departure_sequence(self, *, trigger: str = "arp_timeout") -> None:
        """Gradual fade → lights off → pause Sonos → report away."""
        try:
            steps = 6
            interval = self._config.departure_fade_seconds / steps

            # Get current brightness levels
            lights = await self._hue.get_all_lights()
            if not lights:
                return

            initial_bri = {
                light["light_id"]: light.get("bri", 100)
                for light in lights
                if light.get("on", False)
            }

            for step in range(1, steps + 1):
                progress = step / steps
                for light_id, start_bri in initial_bri.items():
                    new_bri = max(1, int(start_bri * (1 - progress)))
                    await self._hue.set_light(
                        light_id,
                        {"bri": new_bri, "transitiontime": int(interval * 10)},
                    )
                await asyncio.sleep(interval)

            # Final: all lights off
            await self._hue.set_all_lights({"on": False})

            # Pause Sonos if playing
            if self._sonos and self._sonos.connected:
                try:
                    status = await self._sonos.get_status()
                    if status.get("state") == "PLAYING":
                        await self._sonos.pause()
                        logger.info("Sonos paused on departure")
                except Exception as e:
                    logger.warning("Failed to pause Sonos: %s", e)

            # Report away to automation engine
            await self._automation.report_activity("away", "presence")

            self._state = "away"
            # _away_since was set at _on_departure entry; don't reset it here
            # (preserves the actual disconnect timestamp for flap-gate math).
            await self._broadcast_state()
            logger.info("Departure complete — all lights off, mode=away")

            # Log event. Tag with trigger so the DB can distinguish a
            # Shortcut-driven departure from an ARP-timeout one — needed
            # for diagnosing iOS WiFi flap rates. Rule engine falls back
            # to _DEFAULT_SOURCE_WEIGHT for unknown strings, which equals
            # the old "presence" weight, so learning behavior is unchanged.
            if self._event_logger:
                await self._event_logger.log_mode_change(
                    mode="away",
                    previous_mode="idle",
                    source=f"presence:{trigger}",
                )

        except asyncio.CancelledError:
            logger.info("Departure sequence cancelled — phone reappeared")
            raise
        except Exception as e:
            logger.error("Departure sequence error: %s", e, exc_info=True)
            self._state = "away"
            self._away_since = datetime.now(tz=TZ)

    # ------------------------------------------------------------------
    # Arrival
    # ------------------------------------------------------------------

    async def _on_arrival(self, *, force_ceremony: bool = False) -> None:
        """
        Start the arrival sequence as a background task.

        ``force_ceremony`` bypasses the short-absence gate in
        ``_arrival_sequence``. Set by the Shortcut path, where a
        WiFi disconnect+reconnect is explicit "left and returned"
        evidence — the ceremony should always fire, regardless of
        how brief the trip was.
        """
        # Cancel any in-progress departure
        if self._departure_task and not self._departure_task.done():
            self._departure_task.cancel()
            self._departure_task = None
            logger.info("Departure cancelled — phone came back")

        # Calculate how long the user was away
        now = datetime.now(tz=TZ)
        duration_away = (
            now - self._away_since
            if self._away_since
            else timedelta(hours=2)  # Default to full ceremony
        )

        self._state = "arriving"
        self._away_since = None
        logger.info(
            "Arrival detected — away for %d minutes%s",
            int(duration_away.total_seconds() / 60),
            " (forced ceremony)" if force_ceremony else "",
        )
        self._arrival_task = asyncio.create_task(
            self._arrival_sequence(duration_away, force_ceremony=force_ceremony)
        )

    async def _arrival_sequence(
        self,
        duration_away: timedelta,
        *,
        force_ceremony: bool = False,
    ) -> None:
        """
        Choreographed welcome-home sequence.

        When ``force_ceremony`` is False (ARP-detected arrivals), absences
        shorter than ``short_absence_threshold`` skip the ceremony and
        just restore lights. When True (Shortcut-fired arrivals), the
        full sequence always runs.
        """
        try:
            now = datetime.now(tz=TZ)
            time_of_day = self._classify_time(now.hour)
            away_minutes = duration_away.total_seconds() / 60

            # iOS WiFi-flap gate. Threshold differs by arrival source:
            # Shortcut-fired arrivals (force_ceremony=True) get a tight
            # 2-min filter because iOS already provided an explicit
            # connect event — a real trip well exceeds 2 min and a true
            # flap is sub-minute. ARP-only arrivals get 5 min because
            # ARP can miss the phone during iOS power-save for 3–5 min
            # stretches even when the phone is physically home.
            flap_threshold = (
                FLAP_THRESHOLD_MINUTES_SHORTCUT
                if force_ceremony
                else FLAP_THRESHOLD_MINUTES_ARP
            )
            if away_minutes < flap_threshold:
                logger.info(
                    "Arrival: brief disconnect (%d min, threshold %d) — "
                    "treating as flap, no ceremony",
                    int(away_minutes), flap_threshold,
                )
                if self._automation.current_mode in ("idle", "away"):
                    await self._automation._apply_time_based()
                else:
                    await self._automation._apply_mode(
                        self._automation.current_mode
                    )
                self._state = "home"
                await self._broadcast_state()
                return

            # Short absence (<30 min) — just restore lights, skip ceremony.
            # Shortcut-sourced arrivals bypass this: a WiFi
            # disconnect+reconnect is explicit evidence of a real trip,
            # however brief, and always deserves the welcome sequence.
            if (
                not force_ceremony
                and away_minutes < self._config.short_absence_threshold / 60
            ):
                logger.info(
                    "Short absence (%d min) — restoring lights only",
                    int(away_minutes),
                )
                if self._automation.current_mode in ("idle", "away"):
                    await self._automation._apply_time_based()
                else:
                    await self._automation._apply_mode(
                        self._automation.current_mode
                    )
                self._state = "home"
                await self._broadcast_state()
                return

            # --- Light choreography wave ---
            light_state = ARRIVAL_LIGHT_STATES.get(time_of_day, ARRIVAL_LIGHT_STATES["evening"])

            for light_id in ARRIVAL_WAVE_ORDER:
                await self._hue.set_light(
                    light_id,
                    {**light_state, "transitiontime": 10},  # 1s ramp
                )
                await asyncio.sleep(1.0)

            # Brief pause before TTS
            await asyncio.sleep(0.5)

            # --- Adaptive TTS greeting ---
            greeting = self._build_greeting(time_of_day, duration_away)
            if greeting:
                try:
                    await self._tts.speak(
                        greeting, volume=self._config.arrival_volume
                    )
                except Exception as e:
                    logger.warning("Arrival TTS failed: %s", e)

            # --- Dynamic effect ---
            effect = self._pick_arrival_effect(time_of_day)
            if effect and self._hue_v2 and self._hue_v2.connected:
                try:
                    await self._hue_v2.set_effect_all(effect)
                    logger.info("Arrival effect: %s", effect)
                except Exception as e:
                    logger.warning("Arrival effect failed: %s", e)

            # --- Music auto-play ---
            music_mode = ARRIVAL_MUSIC_MODES.get(time_of_day)
            if music_mode and self._music_mapper and self._sonos.connected:
                try:
                    await self._music_mapper.on_mode_change(music_mode)
                    logger.info("Arrival music: mode=%s", music_mode)
                except Exception as e:
                    logger.warning("Arrival music failed: %s", e)

            # --- Hand off to normal automation ---
            self._state = "home"
            await self._broadcast_state()
            logger.info("Arrival sequence complete — normal automation resumes")

        except asyncio.CancelledError:
            logger.info("Arrival sequence cancelled")
            self._state = "home"
            raise
        except Exception as e:
            logger.error("Arrival sequence error: %s", e, exc_info=True)
            self._state = "home"

    # ------------------------------------------------------------------
    # Greeting builder
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_time(hour: int) -> str:
        """Map hour to time-of-day category."""
        if 5 <= hour < 12:
            return "morning"
        if 12 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 21:
            return "evening"
        return "night"

    def _build_greeting(
        self,
        time_of_day: str,
        duration_away: timedelta,
    ) -> Optional[str]:
        """Build contextual TTS greeting text. Returns None for night."""
        if time_of_day == "night":
            return None

        parts: list[str] = []

        # Time-aware opener
        openers = {
            "morning": "Good morning!",
            "afternoon": "Welcome back.",
            "evening": "Welcome home.",
        }
        parts.append(openers.get(time_of_day, "Hey."))

        # Weather
        try:
            weather = (
                self._weather_service.get_cached()
                if self._weather_service
                else None
            )
            if weather:
                temp = weather.get("temp")
                desc = weather.get("description", "")
                if temp is not None:
                    parts.append(f"It's {temp} degrees and {desc.lower()}.")

                # Severe weather alerts
                alerts = weather.get("alerts")
                if alerts:
                    event = alerts[0].get("event", "weather alert")
                    parts.append(f"Heads up, there's a {event} active.")
        except Exception:
            pass  # Don't let weather errors block the greeting

        # Duration context
        hours_away = duration_away.total_seconds() / 3600
        if hours_away >= 8:
            parts.append("You've been out for a while.")
        elif hours_away >= 2:
            parts.append(
                f"You were out about {int(hours_away)} hours."
            )

        return " ".join(parts)

    def _pick_arrival_effect(self, time_of_day: str) -> Optional[str]:
        """Choose arrival effect based on weather and time."""
        # Weather overrides first
        try:
            weather = (
                self._weather_service.get_cached()
                if self._weather_service
                else None
            )
            if weather:
                desc = weather.get("description", "").lower()
                for keyword, effect in WEATHER_EFFECT_OVERRIDES.items():
                    if keyword in desc:
                        return effect
        except Exception:
            pass

        return ARRIVAL_EFFECTS.get(time_of_day)

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def _broadcast_state(self) -> None:
        """Broadcast presence state to all WebSocket clients."""
        if self._ws_manager:
            await self._ws_manager.broadcast(
                "presence_update", self.get_status()
            )
