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
    ("social", "sleeping", "working", "cooking", "gaming", "watching")
)
WEATHER_EFFECT_SKIP_MODES = WEATHER_SKIP_MODES | frozenset(("relax",))


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
    def authority_known(self) -> bool:
        """Whether local effect ownership has been reconciled with the bridge."""
        return self._tracker_known

    @property
    def transition_boundary(self) -> LightingTransitionBoundary:
        """Shared Hue serialization boundary used by all overlapping writers."""
        return self._transition_boundary

    async def _mutate(self, write, validator=None):
        try:
            return await self._transition_boundary.run_write(write, validator=validator)
        except asyncio.CancelledError:
            self._tracker_known = False
            raise

    async def _mutate_many(self, writes, validator=None):
        try:
            return await self._transition_boundary.write_many(
                writes, validator=validator,
            )
        except asyncio.CancelledError:
            self._tracker_known = False
            raise

    def _publish_transition_checkpoint(self, producer: str, light_ids=None):
        authority = self._transition_boundary.authority
        authority.invalidate(light_ids)
        return authority.issue(producer, light_ids, intent_only=True)

    def release_light_ids(self) -> set[str]:
        """All mapped lamps touched by the bridge-wide no-effect release."""
        mapped = getattr(self._hue_v2, "mapped_light_ids", None)
        return set(mapped or ALL_LIGHT_IDS)

    def acknowledge_static_replacement(self, light_ids: set[str]) -> None:
        """Reconcile tracker after a leased snapshot's acknowledged Hue writes.

        Explicit CT/HSB targets cancel each fixture's bridge effect. Partial
        coverage cannot prove a bridge-wide release and therefore fails closed.
        """
        if not self._transition_boundary.held_by_current_task:
            raise RuntimeError("Static replacement acknowledgement requires boundary")
        self._transition_boundary.authority.invalidate()
        if self._tracker_known and self._active_name is None:
            return
        scope = set(self._active_lights or self.release_light_ids())
        if scope <= light_ids:
            self._active_name = None
            self._active_lights = None
            self._tracker_known = True
        else:
            self._tracker_known = False

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
        """Transition effects only while the original semantic intent survives."""
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

        checkpoint = self._publish_transition_checkpoint("effect_reconcile")
        authority = self._transition_boundary.authority
        async with self._transition_boundary.serialized():
            current = lambda: authority.valid(checkpoint)
            if not current():
                return False

            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required) or not current():
                logger.warning(
                    "Effect transition aborted: safety incomplete/stale desired=%s required=%s",
                    desired_effect, sorted(required),
                )
                return False

            await self._transition_boundary.wait_for_settle(required)
            if not current():
                return False
            stopped = await self._mutate(
                self._hue_v2.stop_effect_all, validator=current,
            )
            if stopped is not True:
                logger.warning(
                    "Effect transition aborted: no_effect release failed desired=%s",
                    desired_effect,
                )
                return False
            if not current():
                self._tracker_known = False
                return False

            self._active_name = None
            self._active_lights = None
            self._tracker_known = True
            if not desired_effect:
                logger.info("Effect transition complete: released to static")
                return True

            await asyncio.sleep(self.STOP_START_GUARD_SECONDS)
            if not current():
                self._tracker_known = False
                return False
            if desired_lights is None:
                started = await self._mutate(
                    lambda: self._hue_v2.set_effect_all(desired_effect),
                    validator=current,
                )
            else:
                results = await self._mutate_many(
                    [
                        lambda target=lid: self._hue_v2.set_effect(
                            target, desired_effect,
                        )
                        for lid in desired_lights
                    ],
                    validator=current,
                )
                started = all(result is True for result in results)
            if started is not True or not current():
                self._tracker_known = False
                logger.warning(
                    "Effect start failed/stale after safe release: effect=%s lights=%s",
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
        on_complete: Callable[[], None] | None = None,
        before_transition: Callable[[], Awaitable[None]] | None = None,
    ) -> bool:
        """Run a scene replacement only while its original intent is current."""
        if not self._hue_v2 or not self._hue_v2.connected:
            return False
        required = self.release_light_ids()
        checkpoint = self._publish_transition_checkpoint("scene_transition")
        authority = self._transition_boundary.authority

        async with self._transition_boundary.serialized():
            current = lambda: authority.valid(checkpoint)
            if not current():
                return False
            if before_transition is not None:
                await before_transition()
                if not current():
                    return False

            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required) or not current():
                logger.warning("Scene transition aborted: safety incomplete/stale")
                return False
            await self._transition_boundary.wait_for_settle(required)
            if not current():
                return False

            if await self._mutate(
                self._hue_v2.stop_effect_all, validator=current,
            ) is not True:
                logger.warning("Scene transition aborted: no_effect release failed")
                return False
            if not current():
                self._tracker_known = False
                return False

            self._active_name = None
            self._active_lights = None
            self._tracker_known = True

            if await self._mutate(action, validator=current) is not True:
                return False
            if not current():
                self._tracker_known = False
                return False

            desired_effect, desired_lights = self._normalize_desired(desired)
            if not desired_effect:
                if on_complete is not None:
                    on_complete()
                return True

            await asyncio.sleep(self.STOP_START_GUARD_SECONDS)
            if not current():
                self._tracker_known = False
                return False
            if desired_lights is None:
                started = await self._mutate(
                    lambda: self._hue_v2.set_effect_all(desired_effect),
                    validator=current,
                )
            else:
                results = await self._mutate_many(
                    [
                        lambda target=light_id: self._hue_v2.set_effect(
                            target, desired_effect,
                        )
                        for light_id in desired_lights
                    ],
                    validator=current,
                )
                started = all(result is True for result in results)
            if started is not True or not current():
                self._tracker_known = False
                return False

            self._active_name = desired_effect
            self._active_lights = desired_lights
            if on_complete is not None:
                on_complete()
            return True

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
        checkpoint = self._publish_transition_checkpoint("effect_reconcile_light")
        authority = self._transition_boundary.authority
        async with self._transition_boundary.serialized():
            current = lambda: authority.valid(checkpoint)
            if not current():
                return False
            safety_result = await establish_safety(required)
            if not self._safety_covers(safety_result, required) or not current():
                return False
            await self._transition_boundary.wait_for_settle(required)
            if not current():
                return False
            effect = desired_effect or "no_effect"
            success = await self._mutate(
                lambda: self._hue_v2.set_effect(str(light_id), effect),
                validator=current,
            )
            # A per-light action cannot prove the bridge-wide tracker shape.
            self._tracker_known = False
            return success is True and current()

    async def stop_all(self) -> bool:
        """Direct stop_effect_all under one semantic authority checkpoint."""
        if not self._hue_v2 or not self._hue_v2.connected:
            return False
        if self._active_name is None:
            return True
        checkpoint = self._publish_transition_checkpoint("effect_stop_all")
        authority = self._transition_boundary.authority
        async with self._transition_boundary.serialized():
            current = lambda: authority.valid(checkpoint)
            if not current():
                return False
            stopped = await self._mutate(
                self._hue_v2.stop_effect_all,
                validator=current,
            )
            if stopped is True and current():
                self._active_name = None
                self._active_lights = None
                self._tracker_known = True
                return True
            if stopped is True:
                self._tracker_known = False
            return False

    def get_desired_effect(
        self, mode: str, period: str,
    ) -> Optional[str | dict[str, Any]]:
        """Determine what dynamic effect should be active for a mode.

        Returns either:
          - None                                   (no effect)
          - str                                    (legacy caller, all lights)
          - {"effect": name, "lights": list|None}  (mode-specific, per-light scope)

        Sleeping, social, relax, and watching are static modes. Relax and
        watching still receive their ordinary static weather/light-state
        composition, but never an automatic Hue dynamic effect; explicit
        manual effect commands remain separate.
        """
        if mode in ("sleeping", "social", "relax", "watching"):
            return None
        effect_map = EFFECT_AUTO_MAP.get(mode, {})
        auto_effect = effect_map.get(period)
        if auto_effect is None and period == "late_night":
            auto_effect = effect_map.get("night")
        if auto_effect:
            return auto_effect
        if mode in WEATHER_EFFECT_SKIP_MODES:
            return None
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
            actuator_getter = getattr(self._weather_service, "get_actuator_context", None)
            if callable(actuator_getter):
                context = actuator_getter()
                weather = context.get("weather") if isinstance(context, dict) else None
            else:
                weather = self._weather_service.get_cached()
            if not isinstance(weather, dict):
                return None
        except Exception:
            return None
        desc = weather.get("description", "").lower()
        for keyword, effect in WEATHER_EFFECT_MAP.items():
            if keyword in desc:
                return effect
        return None
