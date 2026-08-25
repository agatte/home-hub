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
from typing import Any, Awaitable, Callable, Optional

from backend.services.light_state_calculator import (
    ALL_LIGHT_IDS,
    AUTOMATIC_EFFECT_LIGHT_IDS,
    EFFECT_AUTO_MAP,
)
from backend.services.lighting_transition_boundary import LightingTransitionBoundary

logger = logging.getLogger("home_hub.automation.effects")


WEATHER_EFFECT_MAP: dict[str, str] = {
    "thunderstorm": "sparkle",
    # Rain previously triggered candle as a weather overlay; removed
    # 2026-05-09 because candle was locking color state and bleeding into
    # other modes. Rainy weather no longer fires an automatic overlay.
    "snow": "opal",
}

WEATHER_SKIP_MODES = frozenset(
    ("social", "sleeping", "working", "cooking", "gaming")
)


class EffectManager:
    """Owns the active Hue v2 effect target and the stop/start dance."""

    STOP_START_GUARD_SECONDS = 0.5

    def __init__(
        self,
        hue_v2,
        weather_service=None,
        transition_boundary: LightingTransitionBoundary | None = None,
    ) -> None:
        self._hue_v2 = hue_v2
        self._weather_service = weather_service
        self._transition_boundary = transition_boundary or LightingTransitionBoundary(
            None,
        )
        self._active_name: Optional[str] = None
        self._active_lights: Optional[list[str]] = None
        # False after process start: bridge state is unknown even though the
        # local active-name slot is empty. A successful release/start makes
        # the tracker authoritative and lets steady-state None reapplies no-op.
        self._tracker_known = False

    @property
    def active_name(self) -> Optional[str]:
        return self._active_name

    @property
    def active_lights(self) -> Optional[list[str]]:
        return self._active_lights

    @property
    def transition_boundary(self) -> LightingTransitionBoundary:
        """Shared Hue serialization boundary used by all overlapping writers."""
        return self._transition_boundary

    def release_light_ids(self) -> set[str]:
        """All mapped lamps touched by the bridge-wide no-effect release."""
        mapped = getattr(self._hue_v2, "mapped_light_ids", None)
        return set(mapped or ALL_LIGHT_IDS)

    def needs_reconcile(self, desired: Optional[str | dict[str, Any]]) -> bool:
        """Whether this desired target requires an effect lifecycle change."""
        desired_effect, desired_lights = self._normalize_desired(desired)
        if not self._tracker_known:
            return True
        return not (
            desired_effect == self._active_name
            and desired_lights == self._active_lights
        )

    @staticmethod
    def _normalize_desired(
        desired: Optional[str | dict[str, Any]],
    ) -> tuple[Optional[str], Optional[list[str]]]:
        if desired is None:
            return None, None
        if isinstance(desired, str):
            return desired, None
        return desired.get("effect"), desired.get("lights")

    @staticmethod
    def _safety_covers(result: Any, required: set[str]) -> bool:
        covers = getattr(result, "covers", None)
        if covers is not None:
            return bool(covers(required))
        return result is True

    async def reconcile(
        self,
        desired: Optional[str | dict[str, Any]],
        establish_safety: Optional[
            Callable[[set[str]], Awaitable[Any]]
        ] = None,
    ) -> bool:
        """
        Transition from the currently-active v2 effect to the desired one.

        The supplied safety callback runs inside the shared transition
        boundary. It must establish an acknowledged static target for every
        mapped lamp; this manager then waits for those transitions to settle
        before sending no_effect. Missing or partial safety aborts the release.

        `desired` accepts three shapes:
          - None:                 no effect should be active
          - str (e.g., "candle"): apply effect to all lights (legacy shape for
                                  callers that explicitly need bridge-wide scope)
          - dict {"effect": name, "lights": list[str] | None}:
              explicit — `lights=None` means all mapped lights; a list scopes
              the effect to specific v1 light IDs (e.g., candle on living-room
              lamps while kitchen pendants stay static in relax mode).

        The same-effect short-circuit kicks in only when BOTH the effect name
        and the target light set match — repeated candle/glisten cycles with
        the same scope preserve the brightness base on the bridge. Unknown
        tracker state always calls stop_effect_all after safety establishment.
        Once a successful release makes the tracker certain, repeated static
        reapplies short-circuit and avoid a transition-duration wait.

        A 0.5s guard separates stop and start so the two commands don't race.
        """
        if not self._hue_v2 or not self._hue_v2.connected:
            return False

        desired_effect, desired_lights = self._normalize_desired(desired)

        if not self.needs_reconcile(desired):
            return True

        required = self.release_light_ids()
        if establish_safety is None:
            logger.warning(
                "Effect transition aborted: no safety establisher desired=%s",
                desired_effect,
            )
            return False

        async with self._transition_boundary.serialized():
            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required):
                logger.warning(
                    "Effect transition aborted: safety incomplete desired=%s required=%s",
                    desired_effect, sorted(required),
                )
                return False

            await self._transition_boundary.wait_for_settle(required)
            stopped = await self._hue_v2.stop_effect_all()
            if stopped is not True:
                logger.warning(
                    "Effect transition aborted: no_effect release failed desired=%s",
                    desired_effect,
                )
                return False
            self._active_name = None
            self._active_lights = None
            self._tracker_known = True

            if not desired_effect:
                logger.info("Effect transition complete: released to static")
                return True

            await asyncio.sleep(self.STOP_START_GUARD_SECONDS)
            if desired_lights is None:
                started = await self._hue_v2.set_effect_all(desired_effect)
            else:
                results = await asyncio.gather(*(
                    self._hue_v2.set_effect(lid, desired_effect)
                    for lid in desired_lights
                ))
                started = all(result is True for result in results)
            if started is not True:
                logger.warning(
                    "Effect start failed after safe release: effect=%s lights=%s",
                    desired_effect, desired_lights,
                )
                return False
            self._active_name = desired_effect
            self._active_lights = desired_lights
            self._tracker_known = True
            logger.info(
                "Effect transition complete: effect=%s lights=%s",
                desired_effect, desired_lights,
            )
            return True

    async def replace_with_action(
        self,
        action: Callable[[], Awaitable[bool]],
        establish_safety: Callable[[set[str]], Awaitable[Any]],
        desired: Optional[str | dict[str, Any]] = None,
    ) -> bool:
        """Safely release any effect, then run a serialized scene action."""
        if not self._hue_v2 or not self._hue_v2.connected:
            return False
        required = self.release_light_ids()
        async with self._transition_boundary.serialized():
            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required):
                logger.warning("Scene transition aborted: safety incomplete")
                return False
            await self._transition_boundary.wait_for_settle(required)
            if await self._hue_v2.stop_effect_all() is not True:
                logger.warning("Scene transition aborted: no_effect release failed")
                return False
            self._active_name = None
            self._active_lights = None
            self._tracker_known = True
            if await action() is not True:
                return False

            desired_effect, desired_lights = self._normalize_desired(desired)
            if not desired_effect:
                return True
            await asyncio.sleep(self.STOP_START_GUARD_SECONDS)
            if desired_lights is None:
                started = await self._hue_v2.set_effect_all(desired_effect)
            else:
                results = await asyncio.gather(*(
                    self._hue_v2.set_effect(light_id, desired_effect)
                    for light_id in desired_lights
                ))
                started = all(result is True for result in results)
            if started is True:
                self._active_name = desired_effect
                self._active_lights = desired_lights
            return started is True

    async def reconcile_light(
        self,
        light_id: str,
        desired_effect: Optional[str],
        establish_safety: Callable[[set[str]], Awaitable[Any]],
    ) -> bool:
        """Safely replace or release an effect on one mapped light."""
        if not self._hue_v2 or not self._hue_v2.connected:
            return False
        required = {str(light_id)}
        async with self._transition_boundary.serialized():
            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required):
                return False
            await self._transition_boundary.wait_for_settle(required)
            effect = desired_effect or "no_effect"
            success = await self._hue_v2.set_effect(str(light_id), effect)
            # A per-light action cannot prove the bridge-wide tracker shape.
            self._tracker_known = False
            return success is True

    async def stop_all(self) -> bool:
        """Direct stop_effect_all + clear tracker.

        Bypasses the safe-release establishment in `reconcile`; callers that
        can expose a bridge effect's raw state must use `reconcile` instead.
        """
        if not self._hue_v2 or not self._hue_v2.connected:
            return False
        if self._active_name is None:
            return True
        async with self._transition_boundary.serialized():
            stopped = await self._hue_v2.stop_effect_all()
            if stopped is True:
                self._active_name = None
                self._active_lights = None
                self._tracker_known = True
            return stopped is True

    def get_desired_effect(
        self, mode: str, period: str,
    ) -> Optional[str | dict[str, Any]]:
        """Determine what dynamic effect should be active for a mode.

        Returns either:
          - None                                   (no effect)
          - str                                    (legacy caller, all lights)
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
            return {
                "effect": weather_effect,
                "lights": list(AUTOMATIC_EFFECT_LIGHT_IDS),
            }
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
