"""
LoL champion → bedroom lamp color service.

When the PC agent reports an activity with a ``champion`` factor while
the automation engine is in ``gaming`` mode, this service resolves the
champion to an RGB color (via the ``champion_color_map`` app setting),
converts it to Hue HSB with the same per-light tuning the screen-sync
path uses (L2 fabric-shade sat boost + L5 perceptual luma compensation),
and writes it to both bedroom lamps directly through ``hue_service``.

Bypasses ``AutomationEngine`` reconcile — same pattern as
``ScreenSyncService.apply_color``. Coexistence with screen-sync is
handled at the route level: ``automation.receive_screen_color`` queries
``LoLChampionService.is_owning(light_id)`` and skips owned lamps so the
champion color isn't fighting per-frame screen-sync writes.

Lifecycle:
    1. ``on_activity_report`` is called from the activity POST handler;
       no-op unless mode is gaming AND the report has a champion factor.
    2. ``on_mode_change`` is registered as an AutomationEngine callback;
       any non-gaming mode clears state so screen-sync resumes.

Effects deliberately not handled here. Gaming's ``EFFECT_AUTO_MAP`` is
all ``None`` today, so there's no v2 effect on these lamps to clash
with. If gaming gains an auto-effect in the future, that mapping needs
to scope the effect off L2 + L5 (see
``feedback_bridge_effects_flatten_color.md``).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from backend.services.color_utils import (
    DEFAULT_LUMA_COMP,
    DEFAULT_SAT_BOOST,
    PER_LIGHT_LUMA_COMP,
    PER_LIGHT_SAT_BOOST,
    rgb_to_hue_hsb,
)

if TYPE_CHECKING:
    from backend.api.schemas.automation import ActivityReport
    from backend.services.automation_engine import AutomationEngine
    from backend.services.hue_service import HueService

logger = logging.getLogger("home_hub.lol_champion")

# Target lamps — both bedroom lamps. Matches the user's design choice
# captured in the plan ("Both lamps"); screen-sync gives up its bedroom
# targets while a League match is active.
TARGET_LIGHT_IDS: tuple[str, ...] = ("2", "5")

# App-settings key for the champion → RGB map. Seeded via
# ``scripts/seed_champion_colors.py``; the service reads it on every
# call so a hand-edit through the DB takes effect on the next match.
CHAMPION_COLOR_MAP_KEY = "champion_color_map"

# Fallback color when a champion isn't in the map. Picked to feel like
# the existing gaming-mode baseline (Colts-blue accent on L2 +
# teal-cyan on L5) rather than dropping a new chromatic statement.
DEFAULT_FALLBACK_RGB: tuple[int, int, int] = (80, 140, 220)

# Per-period brightness caps — mirror the gaming-mode L2 baselines from
# ``light_state_calculator.ACTIVITY_LIGHT_STATES["gaming"]``. The
# champion color drives both lamps to the same target; per-light luma
# compensation in ``rgb_to_hue_hsb`` softens L5 separately so the
# clear-glass lamp doesn't blow out.
LOL_BRIGHTNESS_CAPS: dict[str, int] = {
    "day":         240,
    "evening":     150,
    "night":       140,
    "late_night":  110,
}
LOL_MIN_BRIGHTNESS = 60  # Stay visible even on low-luma palettes (Zed, Aphelios).

# Smooth swap when the user changes champions mid-session (rare; ARAM
# rerolls are the realistic case). 10 deciseconds = 1s transition.
LOL_TRANSITIONTIME = 10


class LoLChampionService:
    """Drive bedroom lamps with the active League champion's signature color.

    The service is constructed once at startup with the ``HueService``
    and the ``AutomationEngine`` whose ``current_mode`` it reads.
    """

    def __init__(
        self,
        hue_service: "HueService",
        automation_engine: "AutomationEngine",
    ) -> None:
        self._hue = hue_service
        self._engine = automation_engine
        self._current_champion: Optional[str] = None
        self._current_rgb: Optional[tuple[int, int, int]] = None
        self._owned: set[str] = set()

    # ------------------------------------------------------------------
    # Public query API — consulted by the screen-sync route handler
    # ------------------------------------------------------------------

    def is_owning(self, light_id: str) -> bool:
        """True if this service currently drives ``light_id``."""
        return light_id in self._owned

    def active_lights(self) -> set[str]:
        """All light ids currently driven by this service."""
        return set(self._owned)

    @property
    def current_champion(self) -> Optional[str]:
        return self._current_champion

    @property
    def current_rgb(self) -> Optional[tuple[int, int, int]]:
        return self._current_rgb

    # ------------------------------------------------------------------
    # Activity / mode hooks
    # ------------------------------------------------------------------

    async def on_activity_report(self, report: "ActivityReport") -> None:
        """Handle an inbound ``ActivityReport``.

        No-op unless the engine is in gaming mode and the report carries
        a ``champion`` factor. Picks the RGB from the persisted map and
        delegates to ``apply``.
        """
        if self._engine is None or self._engine.current_mode != "gaming":
            return

        champion = _extract_champion(report)
        if not champion:
            return

        if champion == self._current_champion and self._owned:
            return  # Idempotent — same champion already on the lamps.

        await self.apply(champion)

    async def on_mode_change(self, mode: str) -> None:
        """Clear champion state when the engine leaves gaming."""
        if mode != "gaming":
            await self.clear()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    async def apply(self, champion_name: str) -> None:
        """Look up champion color, write it to both bedroom lamps."""
        rgb = await self._resolve_color(champion_name)
        period = self._resolve_period()
        max_bri = LOL_BRIGHTNESS_CAPS.get(period, LOL_BRIGHTNESS_CAPS["night"])

        for light_id in TARGET_LIGHT_IDS:
            sat_boost = PER_LIGHT_SAT_BOOST.get(light_id, DEFAULT_SAT_BOOST)
            luma_comp = PER_LIGHT_LUMA_COMP.get(light_id, DEFAULT_LUMA_COMP)
            h, s, br = rgb_to_hue_hsb(
                rgb,
                max_brightness=max_bri,
                min_brightness=LOL_MIN_BRIGHTNESS,
                sat_boost=sat_boost,
                luma_comp=luma_comp,
            )
            await self._hue.set_light(light_id, {
                "on": True,
                "hue": int(h),
                "sat": int(s),
                "bri": int(br),
                "transitiontime": LOL_TRANSITIONTIME,
            })
            self._owned.add(light_id)

        self._current_champion = champion_name
        self._current_rgb = rgb
        logger.info(
            "Applied champion color: %s -> rgb=%s, period=%s, lights=%s",
            champion_name, rgb, period, sorted(self._owned),
        )

    async def clear(self) -> None:
        """Drop ownership stamps so screen-sync resumes on next color post."""
        if not self._owned and self._current_champion is None:
            return
        prior_champion = self._current_champion
        self._owned.clear()
        self._current_champion = None
        self._current_rgb = None
        logger.info(
            "Cleared champion color (was %s); screen-sync will resume",
            prior_champion,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _resolve_color(self, champion_name: str) -> tuple[int, int, int]:
        """Read champion_color_map from app_settings, fall back if absent."""
        from backend.api.routes.routines import load_setting

        try:
            mapping: dict[str, Any] = await load_setting(CHAMPION_COLOR_MAP_KEY)
        except Exception as e:
            logger.warning("Failed to load champion_color_map: %s", e)
            mapping = {}

        entry = mapping.get(champion_name) if mapping else None
        if not entry:
            logger.info(
                "Champion '%s' not in color map — using fallback %s",
                champion_name, DEFAULT_FALLBACK_RGB,
            )
            return DEFAULT_FALLBACK_RGB

        try:
            r = int(entry["r"])
            g = int(entry["g"])
            b = int(entry["b"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "champion_color_map entry for '%s' is malformed (%r) — using fallback",
                champion_name, entry,
            )
            return DEFAULT_FALLBACK_RGB

        return (
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
        )

    def _resolve_period(self) -> str:
        """Pull the engine's current time period; default to ``night`` if unavailable."""
        try:
            return self._engine._get_time_period()
        except Exception:
            return "night"


def _extract_champion(report: "ActivityReport") -> Optional[str]:
    """Pull the ``champion`` factor's value off an ``ActivityReport``.

    Pydantic model — `report.factors` is ``Optional[list[dict]]`` per
    ``ActivityReport``. We accept either a plain string under ``value``
    or under ``display``; the PC agent writes both today.
    """
    factors = getattr(report, "factors", None)
    if not factors:
        return None
    for f in factors:
        if not isinstance(f, dict):
            continue
        if f.get("key") != "champion":
            continue
        val = f.get("value") or f.get("display")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None
