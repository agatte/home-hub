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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from backend.database import async_session
from backend.models import LightAdjustment
from backend.services.ml.feature_builder import get_time_period
from backend.services.ml.health_mixin import HealthTrackable
from backend.services.ml.model_manager import ModelManager

logger = logging.getLogger("home_hub.ml")

# Minimum number of manual adjustments per (light, mode, period, weather="any")
# before we trust the learned value over the hardcoded default. Higher for the
# weather-agnostic "any" bucket because it's the cross-condition baseline —
# more samples reduce noise from mixing weathers.
MIN_ADJUSTMENTS = 5

# Minimum samples for a WEATHER-SPECIFIC bucket. Lower than MIN_ADJUSTMENTS
# because the variance is naturally smaller inside a single weather class
# (the user's storm-time preference doesn't blend with their sunny-day one).
# Matches the threshold the brightness-suggestion scanner uses to decide
# whether a bucket is "consistent enough" to surface.
MIN_ADJUSTMENTS_WEATHER = 3

# EMA decay factor — recent adjustments weighted ~3x more than older ones.
EMA_ALPHA = 0.3

# Light properties we learn from manual adjustments.
LEARNABLE_PROPERTIES = ("bri", "hue", "sat", "ct")

# Only learn from user-initiated triggers (not automation or scenes).
USER_TRIGGERS = ("ws", "rest", "all_lights")

# A single slider drag in the dashboard emits ~5-10 WS events at ~250ms
# throttle — each one a separate `light_adjustments` row with trigger="ws".
# Without dedup the learner counts every mid-drag step as an independent
# "you set this" signal: 1 drag = up to 10 fake samples, biased toward the
# drag's transit values rather than the rest value. Collapse consecutive
# same-bucket rows within this window into one observation (last row =
# drag-end).
DRAG_CLUSTER_SECONDS = 3.0

# Sentinel weather class for buckets that should match any weather. Rows
# with NULL weather_class (pre-migration history) and any caller that
# doesn't have a weather classification land in this bucket. Mirrors
# weather_class.WEATHER_ANY for the music bandit.
WEATHER_ANY = "any"

# Kitchen pair: L3 + L4 must learn identical values in pair-enforced modes
# (CLAUDE.md kitchen-pair invariant). Pooling lives in `recalculate`; other
# modes (relax/sleeping/idle/custom scenes) keep independent EMAs.
PAIR_ENFORCED_MODES = frozenset({
    "working", "gaming", "watching", "cooking", "social", "gameday",
})
KITCHEN_PAIR_IDS = ("3", "4")


class LightingPreferenceLearner(HealthTrackable):
    """EMA-based per-light preference learning from manual adjustments.

    Produces an overlay dict keyed by ``(mode, time_period)`` with
    per-light learned values.  The automation engine merges these on
    top of ``ACTIVITY_LIGHT_STATES``.
    """

    def __init__(self, model_manager: ModelManager) -> None:
        self._model_manager = model_manager
        self._preferences: dict[str, dict[str, dict[str, Any]]] = {}
        self._init_health_tracking()
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

    def get_overlay(
        self,
        mode: str,
        time_period: str,
        weather_class: str = WEATHER_ANY,
    ) -> Optional[dict[str, dict]]:
        """Return learned per-light values for a mode + period + weather, or None.

        Looks up the weather-specific bucket first, then falls back to the
        ``WEATHER_ANY`` bucket so legacy (pre-weather) learned values keep
        applying during the transition. Per-light entries from the specific
        bucket override the "any" entries for overlapping lights.

        The returned dict maps light_id → {property: value}, matching
        the structure inside ``ACTIVITY_LIGHT_STATES``.

        Example return::

            {"1": {"bri": 180}, "2": {"bri": 150, "ct": 300}}
        """
        try:
            specific = self._preferences.get(
                f"{mode}:{time_period}:{weather_class}",
            )
            generic = self._preferences.get(
                f"{mode}:{time_period}:{WEATHER_ANY}",
            )
        except Exception as exc:
            self._track_predict(False, exc)
            logger.warning("Lighting overlay lookup failed: %s", exc)
            return None
        self._track_predict(True)
        if not specific and not generic:
            return None
        # Merge: generic ("any") is the floor, specific overrides per-light.
        merged: dict[str, dict] = {}
        if generic:
            for lid, prefs in generic.items():
                merged[lid] = dict(prefs)
        if specific:
            for lid, prefs in specific.items():
                merged[lid] = dict(prefs)
        return merged or None

    def has_weather_pref(
        self,
        mode: str,
        time_period: str,
        weather_class: str,
    ) -> set[str]:
        """Return the set of light_ids with a WEATHER-SPECIFIC learned bri.

        Used by the heuristic fade-out gate (Layer 5): lights in this set
        skip ``apply_functional_weather_brightness`` because the learner
        has accumulated evidence for the exact (mode, period, weather)
        bucket. The "any" bucket is intentionally excluded — that's the
        cross-condition baseline, not a weather-specific preference.
        """
        if weather_class == WEATHER_ANY:
            return set()
        overlay = self._preferences.get(
            f"{mode}:{time_period}:{weather_class}",
        ) or {}
        return {lid for lid, prefs in overlay.items() if "bri" in prefs}

    async def write_learned_pref(
        self,
        light_id: str,
        mode: str,
        time_period: str,
        weather_class: str,
        bri: int,
    ) -> None:
        """Persist a single learned bri value into the WEATHER-SPECIFIC bucket.

        Called from the rule-engine's accept_brightness_suggestion path
        when the user accepts a suggestion through the notification.
        Persists via ModelManager so the value survives restarts.
        """
        slot_key = f"{mode}:{time_period}:{weather_class}"
        if slot_key not in self._preferences:
            self._preferences[slot_key] = {}
        # Preserve any other learned properties for this light_id.
        existing = self._preferences[slot_key].get(light_id, {})
        existing["bri"] = int(bri)
        self._preferences[slot_key][light_id] = existing
        self._model_manager.save_model(
            "lighting_prefs",
            self._preferences,
            metadata={
                "lights_with_learned_values": len({
                    lid
                    for lights in self._preferences.values()
                    for lid in lights
                }),
                "learned_combos": self._count_per_light_combos(),
                "last_write_source": "suggestion_accept",
            },
        )
        logger.info(
            "Learned brightness written: light=%s slot=%s bri=%d",
            light_id, slot_key, bri,
        )

    def _count_per_light_combos(self) -> int:
        # Per-light learned entries — matches recalculate()'s metadata.
        return sum(len(lights) for lights in self._preferences.values())

    def get_status(self) -> dict:
        """Return learner status for the API."""
        light_count = len({
            light_id
            for lights in self._preferences.values()
            for light_id in lights
        })
        return {
            "learned_slots": len(self._preferences),
            "learned_combos": self._count_per_light_combos(),
            "lights_with_preferences": light_count,
            "min_adjustments": MIN_ADJUSTMENTS,
            "ema_alpha": EMA_ALPHA,
        }

    def health(self) -> dict:
        """Health entry for the /health ml block."""
        # Always considered "active" — no shadow concept; the overlay
        # is harmless when empty (just falls through to defaults).
        return HealthTrackable.health(
            self,
            is_shadow=False,
            model_loaded=True,
            extra={
                "learned_slots": len(self._preferences),
                "learned_combos": self._count_per_light_combos(),
            },
        )

    async def retrain(self) -> None:
        """Recalculate preferences from the full adjustment history.

        Called nightly at 4 AM by ``ModelManager.retrain_all()`` and
        on-demand via ``POST /api/learning/lighting/recalculate``.
        """
        await self.recalculate()

    async def recalculate(self) -> None:
        """Query light_adjustments and recompute EMA preferences.

        Produces two parallel sets of buckets:
          1. **Weather-agnostic** ``{mode}:{period}:any`` from ALL rows
             (NULL weather rows + every classified row). MIN_ADJUSTMENTS=5.
          2. **Weather-specific** ``{mode}:{period}:{weather}`` from rows
             whose weather_class is non-NULL. MIN_ADJUSTMENTS_WEATHER=3.

        ``get_overlay(mode, period, weather)`` merges them at read time —
        weather-specific overrides per-light, "any" is the floor.
        """
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(LightAdjustment)
                    .where(LightAdjustment.trigger.in_(USER_TRIGGERS))
                    .where(LightAdjustment.mode_at_time.isnot(None))
                    .order_by(LightAdjustment.timestamp.asc())
                )
                adjustments = list(result.scalars().all())

            if not adjustments:
                logger.info("No user-initiated light adjustments to learn from")
                return

            # Collapse slider-drag micro-steps before grouping. A single
            # drag emits ~5-10 rows in 1.5s — counting each as an independent
            # observation inflates sample_count and biases EMAs toward
            # transit values rather than rest values.
            pre_collapse = len(adjustments)
            adjustments = self._collapse_drag_clusters(adjustments)
            if pre_collapse != len(adjustments):
                logger.debug(
                    "Collapsed %d → %d adjustments (drag-cluster dedup)",
                    pre_collapse, len(adjustments),
                )

            # Group adjustments into two parallel keyspaces:
            #   any_groups: {light_id}:{mode}:{period}:any           — every row
            #   weather_groups: {light_id}:{mode}:{period}:{weather} — non-NULL only
            any_groups: dict[str, list[LightAdjustment]] = defaultdict(list)
            weather_groups: dict[str, list[LightAdjustment]] = defaultdict(list)
            for adj in adjustments:
                period = get_time_period(adj.timestamp)
                any_key = f"{adj.light_id}:{adj.mode_at_time}:{period}:{WEATHER_ANY}"
                any_groups[any_key].append(adj)
                weather = getattr(adj, "weather_class", None)
                if weather:
                    w_key = f"{adj.light_id}:{adj.mode_at_time}:{period}:{weather}"
                    weather_groups[w_key].append(adj)

            # Kitchen-pair pooling: in pair-enforced modes, L3 and L4 share
            # one adjustment stream so they learn identical EMAs. Pooled
            # across both keyspaces. Without this, asymmetric history
            # (2026-04-16 seed: L3=110 vs L4=90) propagates forever and
            # silently desyncs the pendants.
            self._pool_kitchen_pair(any_groups)
            self._pool_kitchen_pair(weather_groups)

            # Compute EMA for each group with enough data
            new_prefs: dict[str, dict[str, dict[str, Any]]] = {}
            learned_count = 0

            for group_key, adjs in any_groups.items():
                if len(adjs) < MIN_ADJUSTMENTS:
                    continue
                light_id, mode, period, _ = group_key.split(":", 3)
                slot_key = f"{mode}:{period}:{WEATHER_ANY}"
                learned = self._compute_ema(adjs, min_count=MIN_ADJUSTMENTS)
                if learned:
                    new_prefs.setdefault(slot_key, {})[light_id] = learned
                    learned_count += 1

            for group_key, adjs in weather_groups.items():
                if len(adjs) < MIN_ADJUSTMENTS_WEATHER:
                    continue
                light_id, mode, period, weather = group_key.split(":", 3)
                slot_key = f"{mode}:{period}:{weather}"
                learned = self._compute_ema(
                    adjs, min_count=MIN_ADJUSTMENTS_WEATHER,
                )
                if learned:
                    new_prefs.setdefault(slot_key, {})[light_id] = learned
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

    async def scan_for_suggestions(
        self,
        *,
        window_days: int = 14,
        ema_alpha: float = EMA_ALPHA,
    ) -> list[dict[str, Any]]:
        """Find (light, mode, period, weather) buckets ready to be suggested.

        Criteria for a candidate:
          * ``MIN_ADJUSTMENTS_WEATHER`` (=3) or more user-triggered rows in
            the last ``window_days`` matching the bucket.
          * Variance is consistent: (max - min) / mean <= 0.20.
          * No existing WEATHER-SPECIFIC learned pref for that bucket
            (deduplicates against already-accepted suggestions).

        Returns the list of candidate dicts. The caller is responsible for
        deduplicating against existing pending/accepted rule_suggestions
        rows before inserting (RuleEngineService.emit_brightness_suggestion
        handles that step so the scanner stays read-only on the DB).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        async with async_session() as session:
            result = await session.execute(
                select(LightAdjustment)
                .where(LightAdjustment.timestamp >= cutoff)
                .where(LightAdjustment.weather_class.isnot(None))
                .where(LightAdjustment.trigger.in_(USER_TRIGGERS))
                .where(LightAdjustment.mode_at_time.isnot(None))
                .where(LightAdjustment.bri_after.isnot(None))
            )
            rows = list(result.scalars().all())

        # Collapse slider-drag micro-steps — see recalculate() for rationale.
        # A drag emits ~5-10 rows in 1.5s; without dedup the suggestion
        # scanner emits candidates from a single user action.
        rows = self._collapse_drag_clusters(rows)

        # Group by (light_id, mode, period, weather_class). Bri values per
        # group are kept ordered so the EMA can be computed for the
        # suggested_bri exactly the way the learner would on accept.
        groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
        for r in rows:
            period = get_time_period(r.timestamp)
            groups[(r.light_id, r.mode_at_time, period, r.weather_class)].append(
                int(r.bri_after),
            )

        # Avoid importing ACTIVITY_LIGHT_STATES at module-load (would create
        # a light_state_calculator → lighting_learner cycle). Late import.
        from backend.services.light_state_calculator import ACTIVITY_LIGHT_STATES

        suggestions: list[dict[str, Any]] = []
        for (light_id, mode, period, weather), bris in groups.items():
            if len(bris) < MIN_ADJUSTMENTS_WEATHER:
                continue
            mean = sum(bris) / len(bris)
            if mean <= 0:
                continue
            if (max(bris) - min(bris)) / mean > 0.20:
                continue  # too inconsistent to suggest as a stable pref
            if light_id in self.has_weather_pref(mode, period, weather):
                continue  # already learned

            # Compute the EMA the same way write_learned_pref + recalculate
            # would, so accepting yields the value the user just saw.
            ema = float(bris[0])
            for v in bris[1:]:
                ema = ema * (1 - ema_alpha) + v * ema_alpha
            suggested_bri = round(ema)

            try:
                base = ACTIVITY_LIGHT_STATES[mode][period][light_id].get("bri")
            except (KeyError, AttributeError):
                base = None

            suggestion = {
                "light_id": light_id,
                "mode": mode,
                "period": period,
                "weather_class": weather,
                "suggested_bri": suggested_bri,
                "sample_count": len(bris),
            }
            if base:
                suggestion["base_bri"] = int(base)
                suggestion["suggested_multiplier"] = round(suggested_bri / base, 2)
            suggestions.append(suggestion)

        return suggestions

    @staticmethod
    def _collapse_drag_clusters(
        rows: list[LightAdjustment],
        window_s: float = DRAG_CLUSTER_SECONDS,
    ) -> list[LightAdjustment]:
        """Collapse slider-drag micro-steps into one observation per cluster.

        A single dashboard slider drag emits one WS event per ~250ms throttle
        tick → 5-10 rows in the table for one user action. Without this
        collapse the learner counts every intermediate step, inflating
        ``sample_count`` and pulling EMAs toward mid-drag transit values
        instead of the rest value.

        Algorithm: walk rows in time order. Consecutive rows sharing the
        same ``(light_id, mode_at_time, weather_class)`` AND within
        ``window_s`` of the previously-kept row are treated as one cluster
        — only the LAST row (drag-end) survives. Different bucket OR a gap
        > window_s starts a new cluster.

        Edge cases:
          * Empty input → empty output.
          * Two real preference moments separated by >window_s → both kept.
          * Kitchen-pair paired writes (L3 then L4 ~250ms apart) cluster
            independently per ``light_id`` — pooling happens afterwards
            in ``_pool_kitchen_pair``.
        """
        if not rows:
            return []
        # Group by bucket first so interleaved paired writes (kitchen-pair
        # drag emits L3@t, L4@t+50ms, L3@t+250ms, L4@t+300ms, ...) don't
        # break consecutive-row detection inside a linear walk.
        per_bucket: dict[
            tuple[Optional[str], Optional[str], Optional[str]],
            list[LightAdjustment],
        ] = defaultdict(list)
        for r in rows:
            per_bucket[(r.light_id, r.mode_at_time, r.weather_class)].append(r)

        out: list[LightAdjustment] = []
        for bucket_rows in per_bucket.values():
            bucket_rows.sort(key=lambda r: r.timestamp)
            last_keep = bucket_rows[0]
            for r in bucket_rows[1:]:
                gap = (r.timestamp - last_keep.timestamp).total_seconds()
                if gap <= window_s:
                    last_keep = r  # advance the cluster's tail
                else:
                    out.append(last_keep)
                    last_keep = r
            out.append(last_keep)
        out.sort(key=lambda r: r.timestamp)
        return out

    @staticmethod
    def _pool_kitchen_pair(
        groups: dict[str, list[LightAdjustment]],
    ) -> None:
        """Pool L3 + L4 adjustment streams in pair-enforced modes (in place).

        Works for any keyspace whose key prefix is ``{light_id}:{mode}:{period}:...``.
        """
        processed_pairs: set[tuple[str, str, str]] = set()
        for key in list(groups.keys()):
            parts = key.split(":")
            if len(parts) < 4:
                continue
            light_id, mode, period, tail = parts[0], parts[1], parts[2], ":".join(parts[3:])
            if light_id not in KITCHEN_PAIR_IDS or mode not in PAIR_ENFORCED_MODES:
                continue
            if (mode, period, tail) in processed_pairs:
                continue
            l3_key = f"3:{mode}:{period}:{tail}"
            l4_key = f"4:{mode}:{period}:{tail}"
            pooled = groups.get(l3_key, []) + groups.get(l4_key, [])
            if pooled:
                groups[l3_key] = pooled
                groups[l4_key] = pooled
            processed_pairs.add((mode, period, tail))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ema(
        adjustments: list[LightAdjustment],
        min_count: int = MIN_ADJUSTMENTS,
    ) -> dict[str, int]:
        """Compute EMA over a list of adjustments for learnable properties.

        Returns a dict of property → rounded integer value for properties
        that have enough non-None values. ``min_count`` lets weather-specific
        buckets accept fewer samples than the weather-agnostic baseline.
        """
        learned: dict[str, int] = {}

        for prop in LEARNABLE_PROPERTIES:
            after_attr = f"{prop}_after"
            values = [
                getattr(adj, after_attr)
                for adj in adjustments
                if getattr(adj, after_attr) is not None
            ]
            if len(values) < min_count:
                continue

            # EMA: start from the first value, accumulate
            ema = float(values[0])
            for val in values[1:]:
                ema = ema * (1 - EMA_ALPHA) + val * EMA_ALPHA

            learned[prop] = round(ema)

        return learned
