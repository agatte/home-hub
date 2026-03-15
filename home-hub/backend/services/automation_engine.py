"""
Autonomous light engine — time-based + activity-driven light automation.

Combines time-of-day rules with PC activity detection and ambient noise
monitoring to automatically set the optimal lighting. Manual overrides from
the dashboard take priority and persist until the next activity change or
a 4-hour timeout.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.automation")

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")

# Mode priority — higher index wins when multiple sources report
MODE_PRIORITY = {
    "away": 0,
    "idle": 1,
    "working": 2,
    "watching": 3,
    "social": 4,
    "gaming": 5,
}

# Light states for each activity mode
ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    "gaming": {"on": True, "bri": 150, "hue": 46920, "sat": 254},  # Colts blue
    "working": {"on": True, "bri": 220, "hue": 34000, "sat": 50},  # Cool daylight
    "watching": {"on": True, "bri": 50, "hue": 8000, "sat": 200},  # Movie night
    "social": {"on": True, "bri": 200, "hue": 0, "sat": 254},  # Dynamic (overridden by effect)
    "relax": {"on": True, "bri": 120, "hue": 8000, "sat": 180},  # Warm relaxation
    "movie": {"on": True, "bri": 50, "hue": 8000, "sat": 200},  # Alias for watching
}

# Time-based light states (when no activity override is active)
TIME_RULES = [
    # (start_hour, end_hour, light_state_or_callable)
    (6, 8, "morning_ramp"),  # Gradual warm → daylight
    (8, 18, {"on": True, "bri": 254, "hue": 34000, "sat": 50}),  # Daylight
    (18, 21, {"on": True, "bri": 180, "hue": 8000, "sat": 160}),  # Warm evening
    (21, 24, {"on": True, "bri": 80, "hue": 6000, "sat": 200}),  # Dim warm
    (0, 6, {"on": True, "bri": 1, "hue": 6000, "sat": 200}),  # Ultra dim / sleep
]


def _morning_ramp(minute_in_window: int, window_minutes: int = 120) -> dict[str, Any]:
    """
    Calculate gradual morning light ramp from warm/dim to daylight/bright.

    Args:
        minute_in_window: Minutes since 6:00 AM.
        window_minutes: Total ramp duration (default 120 = 6:00-8:00).

    Returns:
        Light state dict interpolated between warm/dim and daylight/bright.
    """
    progress = min(1.0, max(0.0, minute_in_window / window_minutes))

    # Interpolate brightness: 80 → 254
    bri = int(80 + (254 - 80) * progress)
    # Interpolate hue: 8000 (warm) → 34000 (daylight)
    hue = int(8000 + (34000 - 8000) * progress)
    # Interpolate saturation: 180 (warm saturated) → 50 (daylight desaturated)
    sat = int(180 + (50 - 180) * progress)

    return {"on": True, "bri": bri, "hue": hue, "sat": sat}


class AutomationEngine:
    """
    Combines time-of-day rules and activity reports to control lights.

    The engine runs a background loop that checks every 60 seconds whether
    the time-based state needs updating. Activity reports from the PC agent
    and ambient monitor override time-based rules. Manual overrides from
    the dashboard take highest priority.
    """

    def __init__(self, hue, hue_v2, ws_manager) -> None:
        self._hue = hue
        self._hue_v2 = hue_v2
        self._ws_manager = ws_manager

        # Current state
        self._current_mode: str = "idle"
        self._mode_source: str = "time"
        self._manual_override: bool = False
        self._override_mode: Optional[str] = None
        self._override_time: Optional[datetime] = None
        self._last_activity: Optional[str] = None
        self._last_activity_change: Optional[datetime] = None
        self._last_applied_state: Optional[dict] = None

        # Track if lights were turned off externally (Alexa geofence)
        self._external_off_detected: bool = False

        # Config
        self._enabled: bool = True
        self._override_timeout_hours: int = 4
        self._gaming_effect: Optional[str] = None
        self._social_effect: str = "prism"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        return self._override_mode if self._manual_override else self._current_mode

    @property
    def mode_source(self) -> str:
        return "manual" if self._manual_override else self._mode_source

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    @property
    def override_mode(self) -> Optional[str]:
        return self._override_mode

    @property
    def last_activity_change(self) -> Optional[datetime]:
        return self._last_activity_change

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def override_timeout_hours(self) -> int:
        return self._override_timeout_hours

    @override_timeout_hours.setter
    def override_timeout_hours(self, value: int) -> None:
        self._override_timeout_hours = max(1, value)

    @property
    def gaming_effect(self) -> Optional[str]:
        return self._gaming_effect

    @gaming_effect.setter
    def gaming_effect(self, value: Optional[str]) -> None:
        self._gaming_effect = value

    @property
    def social_effect(self) -> str:
        return self._social_effect

    @social_effect.setter
    def social_effect(self, value: str) -> None:
        self._social_effect = value

    # ------------------------------------------------------------------
    # Activity reporting
    # ------------------------------------------------------------------

    async def report_activity(self, mode: str, source: str) -> None:
        """
        Process an activity report from the PC agent or ambient monitor.

        Args:
            mode: Detected mode (gaming, watching, working, social, idle, away).
            source: Detection source ("process" or "ambient").
        """
        if not self._enabled:
            return

        # Ambient "idle" should not override process-detected activity
        if source == "ambient" and mode == "idle":
            if self._mode_source == "process" and self._current_mode != "idle":
                return

        old_mode = self._current_mode

        # Use priority to resolve conflicts between sources
        current_priority = MODE_PRIORITY.get(self._current_mode, 0)
        new_priority = MODE_PRIORITY.get(mode, 0)

        # Ambient social can override process idle, but not gaming
        if source == "ambient" and mode == "social":
            if self._current_mode == "gaming":
                return  # Gaming takes priority

        # Accept the new mode
        self._current_mode = mode
        self._mode_source = source
        self._last_activity = mode
        self._last_activity_change = datetime.now(tz=TZ)

        # Clear manual override on activity change
        if self._manual_override and old_mode != mode:
            logger.info(
                f"Activity changed ({old_mode} → {mode}) — clearing manual override"
            )
            self._manual_override = False
            self._override_mode = None
            self._override_time = None

        # Clear external off detection on any activity
        if mode not in ("idle", "away"):
            self._external_off_detected = False

        # Apply the appropriate light state
        if not self._manual_override:
            await self._apply_mode(mode)

        # Broadcast mode change
        await self._broadcast_mode()

    async def set_manual_override(self, mode: str) -> None:
        """Set a manual mode override from the dashboard."""
        self._manual_override = True
        self._override_mode = mode
        self._override_time = datetime.now(tz=TZ)
        self._last_activity_change = self._override_time

        logger.info(f"Manual override set: {mode}")
        await self._apply_mode(mode)
        await self._broadcast_mode()

    async def clear_override(self) -> None:
        """Clear the manual override and return to automatic mode."""
        self._manual_override = False
        self._override_mode = None
        self._override_time = None

        logger.info("Manual override cleared — returning to auto")

        # Re-apply current detected mode or time-based
        if self._current_mode in ("idle", "away"):
            await self._apply_time_based()
        else:
            await self._apply_mode(self._current_mode)

        await self._broadcast_mode()

    # ------------------------------------------------------------------
    # Light state application
    # ------------------------------------------------------------------

    async def _apply_mode(self, mode: str) -> None:
        """Apply light state for a given mode."""
        # Stop any active effects first
        if self._hue_v2 and self._hue_v2.connected:
            await self._hue_v2.stop_effect_all()

        if mode in ACTIVITY_LIGHT_STATES:
            state = ACTIVITY_LIGHT_STATES[mode]
            await self._apply_state(state)

            # Apply dynamic effects for certain modes
            if self._hue_v2 and self._hue_v2.connected:
                if mode == "gaming" and self._gaming_effect:
                    await self._hue_v2.set_effect_all(self._gaming_effect)
                elif mode == "social" and self._social_effect:
                    await self._hue_v2.set_effect_all(self._social_effect)
        else:
            # Unknown mode — fall back to time-based
            await self._apply_time_based()

    async def _apply_state(self, state: dict[str, Any]) -> None:
        """Apply a light state to all lights and broadcast updates."""
        if not self._hue or not self._hue.connected:
            return

        # Don't reapply the exact same state
        if state == self._last_applied_state:
            return

        self._last_applied_state = state.copy()
        await self._hue.set_all_lights(state)

        # Broadcast light updates
        lights = await self._hue.get_all_lights()
        for light in lights:
            await self._ws_manager.broadcast("light_update", light)

        logger.info(f"Applied light state: bri={state.get('bri')}, hue={state.get('hue')}")

    async def _apply_time_based(self) -> None:
        """Apply the time-appropriate light state."""
        now = datetime.now(tz=TZ)
        hour = now.hour
        minute = now.minute

        for start, end, rule in TIME_RULES:
            if start <= hour < end:
                if rule == "morning_ramp":
                    minutes_since_start = (hour - start) * 60 + minute
                    state = _morning_ramp(minutes_since_start)
                else:
                    state = rule
                await self._apply_state(state)
                return

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """
        Background task — checks every 60 seconds if lights need updating.

        Handles:
        - Time-based transitions (gradual morning ramp, evening dimming)
        - Manual override timeout (auto-clears after N hours)
        - External off detection (Alexa geofence — don't override)
        """
        logger.info("Automation engine started")

        while True:
            try:
                if not self._enabled:
                    await asyncio.sleep(60)
                    continue

                now = datetime.now(tz=TZ)

                # Check manual override timeout
                if self._manual_override and self._override_time:
                    elapsed = now - self._override_time
                    if elapsed > timedelta(hours=self._override_timeout_hours):
                        logger.info(
                            f"Manual override timed out after "
                            f"{self._override_timeout_hours}h"
                        )
                        await self.clear_override()

                # Check for external off (Alexa geofence)
                if await self._check_external_off():
                    await asyncio.sleep(60)
                    continue

                # If no activity override and no manual override, apply time-based
                if (
                    not self._manual_override
                    and self._current_mode in ("idle", "away")
                ):
                    await self._apply_time_based()

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Automation engine stopped")
                break
            except Exception as e:
                logger.error(f"Automation engine error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _check_external_off(self) -> bool:
        """
        Check if all lights were turned off externally (e.g., Alexa geofence).

        If detected, suppress automation to avoid fighting with Alexa.
        Returns True if we should skip this cycle.
        """
        if not self._hue or not self._hue.connected:
            return False

        lights = await self._hue.get_all_lights()
        all_off = all(not light.get("on", False) for light in lights)

        if all_off and not self._external_off_detected:
            # All lights just turned off — could be Alexa geofence
            self._external_off_detected = True
            logger.info("All lights off (external) — suppressing auto-control")
            return True

        return self._external_off_detected

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def _broadcast_mode(self) -> None:
        """Broadcast the current mode to all WebSocket clients."""
        await self._ws_manager.broadcast("mode_update", {
            "mode": self.current_mode,
            "source": self.mode_source,
            "manual_override": self._manual_override,
        })
