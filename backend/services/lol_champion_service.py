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

import asyncio
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
    from backend.services.websocket_manager import WebSocketManager

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

    owner_name = "league_champion"

    def __init__(
        self,
        hue_service: "HueService",
        automation_engine: "AutomationEngine",
        ws_manager: "Optional[WebSocketManager]" = None,
    ) -> None:
        self._hue = hue_service
        self._engine = automation_engine
        # Optional — when present, apply/clear broadcast a ``champion_color``
        # event so off-bridge surfaces (the desktop peripheral-RGB agent)
        # can mirror the champion's color onto the keyboard + mouse.
        self._ws_manager = ws_manager
        self._current_champion: Optional[str] = None
        self._current_rgb: Optional[tuple[int, int, int]] = None
        self._desired_champion: Optional[str] = None
        self._desired_rgb: Optional[tuple[int, int, int]] = None
        self._owned: set[str] = set()
        self._owned_targets: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public query API — consulted by the screen-sync route handler
    # ------------------------------------------------------------------

    def is_owning(self, light_id: str) -> bool:
        """True if this service currently drives ``light_id``."""
        self._release_stronger_owner_lights()
        return light_id in self._owned

    def active_lights(self) -> set[str]:
        """All light ids currently driven by this service."""
        self._release_stronger_owner_lights()
        return set(self._owned)

    def owned_light_targets(self) -> dict[str, dict]:
        """Detached targets for final-applicator/effect-release safety."""
        self._release_stronger_owner_lights()
        return {
            light_id: target.copy()
            for light_id, target in self._owned_targets.items()
        }

    @property
    def current_champion(self) -> Optional[str]:
        return self._current_champion

    @property
    def current_rgb(self) -> Optional[tuple[int, int, int]]:
        return self._current_rgb

    # ------------------------------------------------------------------
    # Activity / mode hooks
    # ------------------------------------------------------------------

    async def on_activity_report(
        self, report: "ActivityReport", disposition: Optional[dict[str, Any]] = None,
    ) -> None:
        """Handle an inbound ``ActivityReport``.

        No-op unless the engine is in gaming mode and the report carries
        a ``champion`` factor. Picks the RGB from the persisted map and
        delegates to ``apply``.
        """
        if disposition is not None and disposition.get("semantic_disposition") != "accepted":
            return
        if getattr(report, "source", None) != "process":
            return
        if self._engine is None or self._engine.current_mode != "gaming":
            return
        if getattr(self._engine, "_gaming_scene_override", None) is not None:
            self.invalidate_ownership("gaming_scene")
            return
        if getattr(self._engine, "_external_off_detected", False):
            self.invalidate_ownership("external_off")
            return

        self._release_stronger_owner_lights()

        champion = _extract_champion(report)
        if not champion:
            observed_source = (
                disposition.get("observed_source")
                if disposition is not None
                else None
            )
            if observed_source not in {None, "process:desktop"}:
                return
            await self.clear()
            return

        await self.apply(champion)

    async def on_mode_change(self, mode: str) -> None:
        """Clear champion state when the engine leaves gaming."""
        if mode != "gaming":
            released = set(self._owned)
            self.invalidate_ownership("mode_exit")
            if (
                released
                and not getattr(self._engine, "_external_off_detected", False)
            ):
                for light_id in released:
                    self._engine._last_applied_per_light.pop(light_id, None)
                await self._engine.reapply_current_mode(force_resend=True)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    async def apply(self, champion_name: str) -> None:
        """Look up champion color and write it only while Gaming still owns it."""
        expected_game = getattr(self._engine, "current_game", None)
        if not self._gaming_authority_allows(expected_game):
            return
        self._release_stronger_owner_lights()
        rgb, seeded = await self._resolve_color(champion_name)
        period = self._resolve_period()
        max_bri = LOL_BRIGHTNESS_CAPS.get(period, LOL_BRIGHTNESS_CAPS["night"])

        targets: dict[str, dict] = {}
        for light_id in TARGET_LIGHT_IDS:
            if light_id in self._stronger_owner_light_ids():
                continue
            sat_boost = PER_LIGHT_SAT_BOOST.get(light_id, DEFAULT_SAT_BOOST)
            luma_comp = PER_LIGHT_LUMA_COMP.get(light_id, DEFAULT_LUMA_COMP)
            h, s, br = rgb_to_hue_hsb(
                rgb,
                max_brightness=max_bri,
                min_brightness=LOL_MIN_BRIGHTNESS,
                sat_boost=sat_boost,
                luma_comp=luma_comp,
            )
            targets[light_id] = {
                "on": True,
                "hue": int(h),
                "sat": int(s),
                "bri": int(br),
                "transitiontime": LOL_TRANSITIONTIME,
            }

        self._desired_champion = champion_name
        self._desired_rgb = rgb
        pending = {
            light_id: target
            for light_id, target in targets.items()
            if self._owned_targets.get(light_id) != target
        }

        boundary = getattr(self._engine, "_transition_boundary", None)

        async def write_targets() -> None:
            # Color lookup and boundary acquisition are both await points.  Re-check
            # authority here so an older League heartbeat cannot write after Gaming
            # exited, the game changed, Away armed, or an explicit scene takeover
            # started while this coroutine was suspended.
            if not self._gaming_authority_allows(expected_game):
                return
            self._release_stronger_owner_lights()
            stronger = self._stronger_owner_light_ids()
            write_pending = {
                light_id: target
                for light_id, target in pending.items()
                if light_id not in stronger
            }
            results = await asyncio.gather(
                *(
                    self._hue.set_light(light_id, target)
                    for light_id, target in write_pending.items()
                ),
                return_exceptions=True,
            )
            # Engine/game/scene state can change while the bridge request itself
            # is awaiting.  A successful physical write does not grant ownership
            # if the authority that authorized it has since expired; the stronger
            # transition waiting on this boundary will reconcile the bridge next.
            if not self._gaming_authority_allows(expected_game):
                return
            stronger_after_write = self._stronger_owner_light_ids()
            supersede = getattr(
                getattr(self._engine, "_screen_sync", None),
                "supersede_light",
                None,
            )
            for light_id, result in zip(write_pending, results):
                if result is True and light_id not in stronger_after_write:
                    self._owned.add(light_id)
                    self._owned_targets[light_id] = write_pending[light_id].copy()
                    if callable(supersede):
                        supersede(light_id)

        if boundary is None or boundary.held_by_current_task:
            await write_targets()
        else:
            async with boundary.serialized():
                await write_targets()

        fully_established = bool(targets) and (
            set(self._owned_targets) == set(targets)
            and all(self._owned_targets[light_id] == target for light_id, target in targets.items())
        )
        accepted_changed = fully_established and (
            self._current_champion != champion_name or self._current_rgb != rgb
        )
        if fully_established:
            self._current_champion = champion_name
            self._current_rgb = rgb
        logger.info(
            "Champion target: %s rgb=%s period=%s owned=%s pending=%s accepted=%s",
            champion_name, rgb, period, sorted(self._owned), sorted(pending),
            fully_established,
        )
        if accepted_changed:
            await self._broadcast_champion(champion_name, rgb, seeded)

    async def clear(self, *, reapply: bool = True) -> bool:
        """Release ownership and immediately restore the current composed plan."""
        if not self._owned and self._current_champion is None and self._desired_champion is None:
            return True
        if getattr(self._engine, "_external_off_detected", False):
            self.invalidate_ownership("external_off")
            return True
        prior_champion = self._current_champion
        self._release_stronger_owner_lights()
        released = set(self._owned)
        if reapply and released and self._engine.current_mode == "gaming":
            result = await self._engine.reclaim_external_light_release(self, released)
            for light_id in result.successful:
                self._owned.discard(light_id)
                self._owned_targets.pop(light_id, None)
        elif not reapply or self._engine.current_mode != "gaming":
            self.invalidate_ownership("context_release")

        if self._owned:
            logger.warning(
                "Champion release incomplete (was %s); retained=%s",
                prior_champion, sorted(self._owned),
            )
            return False

        self._finish_clear(prior_champion)
        await self._broadcast_champion(None, None, False)
        return True

    async def release_for_scene(self) -> bool:
        """Restore the accepted static plan before native scene activation."""
        return await self.clear()

    def invalidate_ownership(self, reason: str) -> None:
        """Drop stamps without writes after a stronger physical lifecycle event."""
        sync = getattr(self._engine, "_screen_sync", None)
        supersede = getattr(sync, "supersede_light", None)
        if callable(supersede):
            for light_id in self._owned:
                supersede(light_id)
        prior = self._current_champion or self._desired_champion
        self._owned.clear()
        self._owned_targets.clear()
        self._current_champion = None
        self._current_rgb = None
        self._desired_champion = None
        self._desired_rgb = None
        logger.info("Invalidated champion ownership (%s, was %s)", reason, prior)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _gaming_authority_allows(self, expected_game: Optional[str]) -> bool:
        """Whether this in-flight League write still has Gaming authority."""
        if self._engine is None or self._engine.current_mode != "gaming":
            return False
        if getattr(self._engine, "current_game", None) != expected_game:
            return False
        if getattr(self._engine, "_gaming_scene_override", None) is not None:
            return False
        if getattr(self._engine, "_gaming_scene_transition_pending", False):
            return False
        if getattr(self._engine, "_external_off_detected", False):
            return False
        return True

    def _stronger_owner_light_ids(self) -> set[str]:
        """Manual and transit intent outrank this external color writer."""
        return set(getattr(self._engine, "manual_light_overrides", {})) | set(
            getattr(self._engine, "_transit_light_overrides", {}),
        )

    def _release_stronger_owner_lights(self) -> None:
        protected = self._stronger_owner_light_ids()
        self._owned -= protected
        for light_id in protected:
            self._owned_targets.pop(light_id, None)

    def _finish_clear(self, prior_champion: Optional[str]) -> None:
        self._current_champion = None
        self._current_rgb = None
        self._desired_champion = None
        self._desired_rgb = None
        logger.info(
            "Cleared champion color (was %s); composed Gaming restored",
            prior_champion,
        )

    async def _resolve_color(
        self, champion_name: str,
    ) -> tuple[tuple[int, int, int], bool]:
        """Read champion_color_map from app_settings, fall back if absent.

        Returns ``(rgb, seeded)`` — ``seeded`` is True only when the
        champion had an explicit entry in the map (a real signature
        color), False when we dropped to the generic fallback. Downstream
        surfaces (the peripheral-RGB agent) use ``seeded`` to decide
        whether to override their default behavior.
        """
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
            return DEFAULT_FALLBACK_RGB, False

        try:
            r = int(entry["r"])
            g = int(entry["g"])
            b = int(entry["b"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "champion_color_map entry for '%s' is malformed (%r) — using fallback",
                champion_name, entry,
            )
            return DEFAULT_FALLBACK_RGB, False

        return (
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
        ), True

    async def _broadcast_champion(
        self,
        champion: Optional[str],
        rgb: Optional[tuple[int, int, int]],
        seeded: bool,
    ) -> None:
        """Emit a ``champion_color`` WS event (best-effort, no-op if unwired).

        Payload: ``{champion, rgb: [r,g,b] | None, seeded}``. ``rgb`` is a
        plain list for JSON; ``seeded`` lets a consumer ignore generic
        fallback colors. A null ``champion`` signals the override cleared.
        """
        if self._ws_manager is None:
            return
        try:
            await self._ws_manager.broadcast("champion_color", {
                "champion": champion,
                "rgb": list(rgb) if rgb is not None else None,
                "seeded": seeded,
            })
        except Exception:
            logger.debug("champion_color broadcast failed", exc_info=True)

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
