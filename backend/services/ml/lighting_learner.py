"""Adaptive lighting preference learner.

Learns per-light brightness/color preferences from manual adjustment
history using an exponential moving average (EMA).  Produces an overlay
dict that merges on top of the hardcoded ``ACTIVITY_LIGHT_STATES`` in
the automation engine — learned values replace defaults only for
(light, mode, period) combos with enough data.

No external ML libraries required — pure math.
"""

import logging
from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import select

from backend.database import async_session
from backend.models import LightAdjustment
from backend.services.ml.feature_builder import get_time_period
from backend.services.ml.model_manager import ModelManager

logger = logging.getLogger("home_hub.ml")

# Minimum number of manual adjustments per (light, mode, period)
# before we trust the learned value over the hardcoded default.
MIN_ADJUSTMENTS = 5

# EMA decay factor — recent adjustments weighted ~3x more than older ones.
EMA_ALPHA = 0.3

# Light properties we learn from manual adjustments.
LEARNABLE_PROPERTIES = ("bri", "hue", "sat", "ct")

# Only learn from user-initiated triggers (not automation or scenes).
USER_TRIGGERS = ("ws", "rest", "all_lights")


class LightingPreferenceLearner:
    """EMA-based per-light preference learning from manual adjustments.

    Produces an overlay dict keyed by ``(mode, time_period)`` with
    per-light learned values.  The automation engine merges these on
    top of ``ACTIVITY_LIGHT_STATES``.
    """

    def __init__(self, model_manager: ModelManager) -> None:
        self._model_manager = model_manager
        self._preferences: dict[str, dict[str, dict[str, Any]]] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        """Load previously computed preferences from model storage."""
        data = self._model_manager.get_model("lighting_prefs")
        if isinstance(data, dict):
            self._preferences = data
            count = sum(
                len(lights)
                for lights in self._preferences.values()
            )
            logger.info("Loaded lighting preferences: %d light/slot combos", count)
        else:
            logger.info("No existing lighting preferences — starting fresh")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_overlay(self, mode: str, time_period: str) -> Optional[dict[str, dict]]:
        """Return learned per-light values for a mode + period, or None.

        The returned dict maps light_id → {property: value}, matching
        the structure inside ``ACTIVITY_LIGHT_STATES``.

        Example return::

            {"1": {"bri": 180}, "2": {"bri": 150, "ct": 300}}
        """
        key = f"{mode}:{time_period}"
        overlay = self._preferences.get(key)
        if not overlay:
            return None
        return overlay

    def get_status(self) -> dict:
        """Return learner status for the API."""
        combo_count = len(self._preferences)
        light_count = len({
            light_id
            for lights in self._preferences.values()
            for light_id in lights
        })
        return {
            "learned_combos": combo_count,
            "lights_with_preferences": light_count,
            "min_adjustments": MIN_ADJUSTMENTS,
            "ema_alpha": EMA_ALPHA,
        }

    async def retrain(self) -> None:
        """Recalculate preferences from the full adjustment history.

        Called nightly at 4 AM by ``ModelManager.retrain_all()`` and
        on-demand via ``POST /api/learning/lighting/recalculate``.
        """
        await self.recalculate()

    async def recalculate(self) -> None:
        """Query light_adjustments and recompute EMA preferences."""
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(LightAdjustment)
                    .where(LightAdjustment.trigger.in_(USER_TRIGGERS))
                    .where(LightAdjustment.mode_at_time.isnot(None))
                    .order_by(LightAdjustment.timestamp.asc())
                )
                adjustments = result.scalars().all()

            if not adjustments:
                logger.info("No user-initiated light adjustments to learn from")
                return

            # Group adjustments by (light_id, mode, time_period)
            groups: dict[str, list[LightAdjustment]] = defaultdict(list)
            for adj in adjustments:
                period = get_time_period(adj.timestamp)
                key = f"{adj.light_id}:{adj.mode_at_time}:{period}"
                groups[key].append(adj)

            # Compute EMA for each group with enough data
            new_prefs: dict[str, dict[str, dict[str, Any]]] = {}
            learned_count = 0

            for group_key, adjs in groups.items():
                if len(adjs) < MIN_ADJUSTMENTS:
                    continue

                light_id, mode, period = group_key.split(":", 2)
                slot_key = f"{mode}:{period}"

                learned = self._compute_ema(adjs)
                if learned:
                    if slot_key not in new_prefs:
                        new_prefs[slot_key] = {}
                    new_prefs[slot_key][light_id] = learned
                    learned_count += 1

            self._preferences = new_prefs

            # Persist to disk
            self._model_manager.save_model(
                "lighting_prefs",
                new_prefs,
                metadata={
                    "lights_with_learned_values": len({
                        lid
                        for lights in new_prefs.values()
                        for lid in lights
                    }),
                    "total_adjustments_used": len(adjustments),
                    "learned_combos": learned_count,
                },
            )
            logger.info(
                "Lighting preferences recalculated: %d combos from %d adjustments",
                learned_count,
                len(adjustments),
            )

        except Exception as exc:
            logger.error(
                "Failed to recalculate lighting preferences: %s",
                exc,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ema(adjustments: list[LightAdjustment]) -> dict[str, int]:
        """Compute EMA over a list of adjustments for learnable properties.

        Returns a dict of property → rounded integer value for properties
        that have enough non-None values.
        """
        learned: dict[str, int] = {}

        for prop in LEARNABLE_PROPERTIES:
            after_attr = f"{prop}_after"
            values = [
                getattr(adj, after_attr)
                for adj in adjustments
                if getattr(adj, after_attr) is not None
            ]
            if len(values) < MIN_ADJUSTMENTS:
                continue

            # EMA: start from the first value, accumulate
            ema = float(values[0])
            for val in values[1:]:
                ema = ema * (1 - EMA_ALPHA) + val * EMA_ALPHA

            learned[prop] = round(ema)

        return learned
