"""Hue v2 dynamic-effect lifecycle.

Owns the active-effect target (name + light scope) and the stop/start
sequencing. Extracted from `automation_engine.py` so the engine can
focus on light-state application + orchestration.

The manager is stateful but I/O-only on the Hue v2 service — it never
reads light state and doesn't know about modes per se. Mode/period
resolution happens in `get_desired_effect`, which the engine calls
to get the target shape, and then passes back into `reconcile`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.services.light_state_calculator import EFFECT_AUTO_MAP

logger = logging.getLogger("home_hub.automation.effects")


WEATHER_EFFECT_MAP: dict[str, str] = {
    "thunderstorm": "sparkle",
    "rain": "candle",
    "snow": "opal",
}

WEATHER_SKIP_MODES = frozenset(
    ("social", "sleeping", "working", "cooking", "gaming")
)


class EffectManager:
    """Owns the active Hue v2 effect target and the stop/start dance."""

    STOP_START_GUARD_SECONDS = 0.5

    def __init__(self, hue_v2, weather_service=None) -> None:
        self._hue_v2 = hue_v2
        self._weather_service = weather_service
        self._active_name: Optional[str] = None
        self._active_lights: Optional[list[str]] = None

    @property
    def active_name(self) -> Optional[str]:
        return self._active_name

    @property
    def active_lights(self) -> Optional[list[str]]:
        return self._active_lights

    async def reconcile(
        self, desired: Optional[str | dict[str, Any]],
    ) -> None:
        """
        Transition from the currently-active v2 effect to the desired one.

        MUST be called AFTER the new light state / scene is on the bridge,
        so stopping the old effect doesn't pop brightness to 100%. The
        bridge will hold the last-set brightness target and return to it
        once the effect releases.

        `desired` accepts three shapes:
          - None:                 no effect should be active
          - str (e.g., "candle"): apply effect to all lights (legacy shape,
                                  used by weather-effect fallback and callers
                                  that don't need per-light targeting)
          - dict {"effect": name, "lights": list[str] | None}:
              explicit — `lights=None` means all mapped lights; a list scopes
              the effect to specific v1 light IDs (e.g., candle on living-room
              lamps while kitchen pendants stay static in relax mode).

        The same-effect short-circuit kicks in only when BOTH the effect name
        and the target light set match — repeated candle/glisten cycles with
        the same scope preserve the brightness base on the bridge. When
        `desired` is None we always call stop_effect_all (even if our tracker
        agrees none is running) to handle effects activated out-of-band by
        the scenes API, presence/winddown services, or left across a restart.

        A 0.5s guard separates stop and start so the two commands don't race.
        """
        if not self._hue_v2 or not self._hue_v2.connected:
            return

        if desired is None:
            desired_effect: Optional[str] = None
            desired_lights: Optional[list[str]] = None
        elif isinstance(desired, str):
            desired_effect = desired
            desired_lights = None
        else:
            desired_effect = desired.get("effect")
            desired_lights = desired.get("lights")

        if (
            desired_effect
            and desired_effect == self._active_name
            and desired_lights == self._active_lights
        ):
            return

        await self._hue_v2.stop_effect_all()
        self._active_name = None
        self._active_lights = None

        if not desired_effect:
            return

        await asyncio.sleep(self.STOP_START_GUARD_SECONDS)
        if desired_lights is None:
            await self._hue_v2.set_effect_all(desired_effect)
        else:
            await asyncio.gather(*(
                self._hue_v2.set_effect(lid, desired_effect)
                for lid in desired_lights
            ))
        self._active_name = desired_effect
        self._active_lights = desired_lights

    async def stop_all(self) -> None:
        """Direct stop_effect_all + clear tracker.

        Bypasses the same-effect-skip in `reconcile`. Used by sleep mode
        after the dim target is settled on the bridge: the engine writes
        bri=20, sleeps 1.2s for the bridge to hold the target, then calls
        this so the running effect releases without popping brightness.
        """
        if not self._hue_v2 or not self._hue_v2.connected:
            return
        if self._active_name is None:
            return
        await self._hue_v2.stop_effect_all()
        self._active_name = None
        self._active_lights = None

    def get_desired_effect(
        self, mode: str, period: str,
    ) -> Optional[str | dict[str, Any]]:
        """Determine what dynamic effect should be active for a mode.

        Returns either:
          - None                                   (no effect)
          - str                                    (weather fallback, all lights)
          - {"effect": name, "lights": list|None}  (mode-specific, per-light scope)

        Sleeping and social manage their own effects (sleeping = none,
        social = none per Velvet Speakeasy static palette).
        """
        if mode in ("sleeping", "social"):
            return None
        effect_map = EFFECT_AUTO_MAP.get(mode, {})
        auto_effect = effect_map.get(period)
        if auto_effect is None and period == "late_night":
            auto_effect = effect_map.get("night")
        if auto_effect:
            return auto_effect
        weather_effect = self.get_weather_effect()
        if weather_effect and (
            period in ("evening", "night", "late_night")
            or weather_effect == "sparkle"
        ):
            return weather_effect
        return None

    def get_weather_effect(self) -> str | None:
        """Return an effect override based on current weather, or None."""
        if not self._weather_service:
            return None
        try:
            weather = self._weather_service.get_cached()
            if not weather:
                return None
        except Exception:
            return None
        desc = weather.get("description", "").lower()
        for keyword, effect in WEATHER_EFFECT_MAP.items():
            if keyword in desc:
                return effect
        return None
