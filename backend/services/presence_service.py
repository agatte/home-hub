"""
Presence detection service — monitors iPhone on WiFi to detect home/away.

Replaces Alexa geofence with native presence detection. Pings the phone
every 30 seconds. After 10 minutes of no response, triggers a gradual
departure (fade lights, pause Sonos, report away). When the phone
reappears, runs a welcome-home arrival sequence with choreographed
lights, contextual TTS greeting, and music.

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


@dataclass
class PresenceConfig:
    """Persisted presence detection configuration."""

    enabled: bool = True
    phone_ip: str = "192.168.1.148"
    phone_mac: str = "A2:DD:D9:65:EE:F8"
    ping_interval: int = 30
    away_timeout: int = 600               # 10 minutes
    short_absence_threshold: int = 1800   # 30 min — skip ceremony
    arrival_volume: int = 25
    departure_fade_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresenceConfig":
        """Create config from a dict, ignoring unknown keys."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class PresenceService:
    """
    WiFi-based phone presence detection with arrival/departure sequences.

    Runs as a background task in the FastAPI lifespan. Pings the configured
    phone IP every ``ping_interval`` seconds. Transitions:

    - **home → away**: After ``away_timeout`` seconds with no ping response,
      runs a gradual departure sequence (fade lights, pause Sonos).
    - **away → home**: On first successful ping, runs the arrival sequence
      (light wave, TTS greeting, music auto-play).
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
        self._departure_task: Optional[asyncio.Task] = None
        self._arrival_task: Optional[asyncio.Task] = None

        self._is_linux = platform.system() == "Linux"

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

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Background task — ping phone every interval, manage state."""
        logger.info(
            "Presence detection started (phone=%s, timeout=%ds)",
            self._config.phone_ip,
            self._config.away_timeout,
        )

        while True:
            try:
                if not self._config.enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)
                reachable = await self._ping(self._config.phone_ip)

                if reachable:
                    self._consecutive_failures = 0
                    self._last_seen = now

                    if self._state in ("unknown", "startup_away"):
                        # Startup — set home without triggering arrival
                        self._state = "home"
                        logger.info("Initial presence: home")
                    elif self._state in ("away", "departing"):
                        await self._on_arrival()

                else:
                    self._consecutive_failures += 1

                    # After 3 failures, try ARP lookup for IP change
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
                        # so a successful ping next cycle sets "home"
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

            await asyncio.sleep(self._config.ping_interval)

    # ------------------------------------------------------------------
    # Ping / ARP
    # ------------------------------------------------------------------

    async def _ping(self, ip: str) -> bool:
        """ICMP ping with 2-second timeout. Returns True if reachable."""
        try:
            if self._is_linux:
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
            logger.debug("Ping failed for %s: %s", ip, e)
            return False

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

    async def _on_departure(self) -> None:
        """Start the departure sequence as a background task."""
        # Skip departure if a manual override is active. An explicit mode
        # (relax, social, cooking, watching, sleeping, etc.) is strong
        # presence evidence — a 10-min ping silence during live use is
        # almost always phone-side (charger + DND, weak signal, iOS network
        # throttling) rather than an actual departure. Reset the countdown
        # so the next real ping failure is evaluated freshly after the
        # override clears.
        if self._automation and self._automation.manual_override:
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
        logger.info("Departure detected — starting fade sequence")
        self._departure_task = asyncio.create_task(
            self._departure_sequence()
        )

    async def _departure_sequence(self) -> None:
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
            self._away_since = datetime.now(tz=TZ)
            await self._broadcast_state()
            logger.info("Departure complete — all lights off, mode=away")

            # Log event
            if self._event_logger:
                await self._event_logger.log_mode_change(
                    mode="away",
                    previous_mode="idle",
                    source="presence",
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

    async def _on_arrival(self) -> None:
        """Start the arrival sequence as a background task."""
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
            "Arrival detected — away for %d minutes",
            int(duration_away.total_seconds() / 60),
        )
        self._arrival_task = asyncio.create_task(
            self._arrival_sequence(duration_away)
        )

    async def _arrival_sequence(self, duration_away: timedelta) -> None:
        """Choreographed welcome-home sequence."""
        try:
            now = datetime.now(tz=TZ)
            time_of_day = self._classify_time(now.hour)
            away_minutes = duration_away.total_seconds() / 60

            # Short absence (<30 min) — just restore lights, skip ceremony
            if away_minutes < self._config.short_absence_threshold / 60:
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
