"""
Per-light override manager — GH#87 step 4 of the automation_engine
decomposition.

Sole owner of the per-light protection verbs: manual-override stamps
(mark / clear / 4h expiry), the dedup-cache invalidation discipline,
and the transit/desk-exit/corridor override lifecycle (apply → protect
→ prune/clear → revert).

The dicts themselves live on :class:`EngineState` (step 4a) and are
operated on with direct O(1) dict reads/writes — critic #4: the 0.5s
poll/gather hot path must keep direct membership checks, no per-light
method indirection. The applicator side (skip filter, dedup compare in
``_apply_state``) reads the same dicts directly on the engine.

Critic #5: this is NOT a pure dict owner — ``apply_transit_override``
does bridge writes + event logging and reads the effective mode, so the
constructor takes hue / event-logger / current-mode access. Getters are
used because the engine wires some of these after construction.

AutomationEngine keeps thin delegates under the original method names
(``mark_light_manual``, ``apply_transit_override``, …) so external
callers (TransitLightingService, DeskExitKitchenService, WS handler,
tests) are untouched.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from backend.services.automation_constants import TZ
from backend.services.engine_state import EngineState

# Same logger name as the engine so journald output is unchanged.
logger = logging.getLogger("home_hub.automation")


class LightOverrideManager:
    """Manual + transit per-light override lifecycle over an EngineState."""

    def __init__(
        self,
        *,
        state: EngineState,
        hue_getter: Callable[[], Any],
        event_logger_getter: Callable[[], Any],
        current_mode_getter: Callable[[], str],
        reapply_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        self._st = state
        self._hue_getter = hue_getter
        self._event_logger_getter = event_logger_getter
        self._current_mode_getter = current_mode_getter
        self._reapply_mode = reapply_mode

    # ── Manual stamps ───────────────────────────────────────────────────

    def mark_manual(self, light_id: str) -> None:
        """Mark a light as manually adjusted — protects it from automation.

        Per-light overrides are cleared on the next explicit mode change
        (manual override set/cleared) so automation resumes naturally.
        """
        self._st.manual_light_overrides[light_id] = datetime.now(tz=TZ)
        logger.info(f"Light {light_id} marked as manually overridden")

    def clear_manual_stamps(self) -> None:
        """Clear all per-light manual overrides."""
        if self._st.manual_light_overrides:
            logger.info(
                f"Clearing per-light overrides: {list(self._st.manual_light_overrides)}"
            )
            self._st.manual_light_overrides.clear()

    def expire_manual_stamps(self, now: datetime, timeout_hours: int) -> None:
        """Expire stale per-light overrides (same window as the mode-level
        override, tracked per-entry via the datetime stamped in
        ``mark_manual``). Called once per run_loop tick.
        """
        if not self._st.manual_light_overrides:
            return
        cutoff = timedelta(hours=timeout_hours)
        expired = [
            lid for lid, ts in self._st.manual_light_overrides.items()
            if now - ts > cutoff
        ]
        for lid in expired:
            del self._st.manual_light_overrides[lid]
            logger.info(
                f"Per-light override on light {lid} expired "
                f"after {timeout_hours}h"
            )

    # ── Dedup-cache discipline ──────────────────────────────────────────

    def invalidate_dedup_cache(self) -> None:
        """Drop the per-light dedup cache so the next ``_apply_state`` re-sends
        to every light instead of being suppressed as a no-op.

        Single owner for the "force re-apply" discipline. Call wherever the
        bridge may have diverged from ``last_applied_per_light`` (mode
        transitions across a colorspace switch, effect stop/start, config
        hot-reloads, sleep-fade steps, scene drift). Centralized so a new code
        path can't silently reintroduce the stale-cache dedup-skip behind the
        kitchen-pair drift of 2026-05-09 (project_transit_lighting_cache_pop_churn).
        """
        self._st.last_applied_per_light = {}

    def forget_dedup_light(self, light_id: str) -> None:
        """Drop one light from the dedup cache so the next reconcile re-sends
        the mode's state to it. Used when a transit override is cleared/expired
        and the cache would otherwise retain the stale transit value and
        dedup-skip the revert.
        """
        self._st.last_applied_per_light.pop(light_id, None)

    # ── Transit / desk-exit / corridor lifecycle ────────────────────────

    def prune_expired_transit(self) -> None:
        """Remove transit overrides whose deadline has passed.

        Called before the skip filter consults the dict so expired entries
        don't stale-lock automation from reasserting a light.
        """
        if not self._st.transit_light_overrides:
            return
        now = datetime.now(tz=TZ)
        expired = [
            lid for lid, deadline in self._st.transit_light_overrides.items()
            if deadline <= now
        ]
        for lid in expired:
            del self._st.transit_light_overrides[lid]
            # Mirrors clear_transit_override's pop. Without it, the dedup
            # cache retains transit values after deadline expiry and the
            # next reconcile dedup-skips on stale data (kitchen-pair drift
            # 2026-05-09; memory project_transit_lighting_cache_pop_churn).
            self.forget_dedup_light(lid)
        if expired:
            logger.info(
                "Transit overrides auto-expired for lights %s",
                expired,
            )

    async def apply_transit_override(
        self,
        states: dict[str, dict],
        duration_seconds: int = 600,
        transition_time: int = 20,
        trigger: str = "transit",
    ) -> None:
        """Apply temporary per-light brightness, protected from mode reconcile.

        Writes the given per-light states directly to the bridge and protects
        those lights from mode-driven automation until ``clear_transit_override``
        is called or the deadline elapses. Used by ``TransitLightingService``
        (gentle navigation lift) and ``DeskExitKitchenService`` (kitchen
        brighten on desk exit) — both share the same protection slot
        (``transit_light_overrides``) but distinguish themselves via the
        ``trigger`` label written to ``light_adjustments``.

        Args:
            states: light_id → state dict (``{"on": True, "bri": ..., "ct": ...}``)
            duration_seconds: max protection window before auto-expiry
            transition_time: deciseconds for the Hue transition (20 = 2s)
            trigger: label written to light_adjustments.trigger — defaults to
                ``"transit"`` for back-compat; ``DeskExitKitchenService`` passes
                ``"desk_exit_kitchen"`` so analytics can distinguish the two
                paths.
        """
        hue = self._hue_getter()
        if not hue or not hue.connected:
            return

        # Kitchen-pair atomicity: L3 + L4 must move as a unit in functional
        # modes. If the user has manually set one (e.g., L4 at bri=114),
        # transit-overriding only the unstamped one splits the pendants —
        # writes go to L3 directly here, but the next _apply_per_light cycle
        # re-protects L4 (manual stamp) and not L3, leaving them mismatched.
        # Skip the pair entirely when either is manual; L1 still applies.
        # Symptom that motivated this guard: 21 solo-L3 writes / 11 min split
        # on 2026-05-09. Memory: project_transit_lighting_cache_pop_churn.md.
        if "3" in states and "4" in states:
            kitchen_manual = (
                "3" in self._st.manual_light_overrides
                or "4" in self._st.manual_light_overrides
            )
            if kitchen_manual:
                stamped = next(
                    lid for lid in ("3", "4")
                    if lid in self._st.manual_light_overrides
                )
                logger.info(
                    "%s skipped kitchen pair (L3/L4) — manual override on light %s",
                    trigger, stamped,
                )
                states = {
                    lid: s for lid, s in states.items() if lid not in ("3", "4")
                }
                if not states:
                    return

        deadline = datetime.now(tz=TZ) + timedelta(seconds=duration_seconds)
        tasks = []
        # Capture before-state for event logging — same pattern as
        # _apply_per_light. Without this, transit writes were invisible to
        # light_adjustments queries (2026-05-12 incident: 107 transit cycles
        # in 30 min produced zero rows in the analytics surface).
        pre_values: dict[str, dict] = {}
        for light_id, state in states.items():
            pre_values[light_id] = (
                self._st.last_applied_per_light.get(light_id) or {}
            ).copy()
            cmd = {**state, "transitiontime": transition_time}
            tasks.append(hue.set_light(light_id, cmd))
            self._st.transit_light_overrides[light_id] = deadline
            # Seed dedup so a concurrent reconcile cycle doesn't re-send the
            # previous mode state for these lights before the skip filter runs.
            self._st.last_applied_per_light[light_id] = {k: v for k, v in state.items() if k != "transitiontime"}
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            "%s override applied to lights %s (expires %s)",
            trigger, list(states.keys()),
            deadline.strftime("%H:%M:%S"),
        )
        event_logger = self._event_logger_getter()
        if event_logger:
            current_mode = self._current_mode_getter()
            for light_id, state in states.items():
                prev = pre_values.get(light_id, {})
                await event_logger.log_light_adjustment(
                    light_id=light_id,
                    bri_before=prev.get("bri"), bri_after=state.get("bri"),
                    hue_before=prev.get("hue"), hue_after=state.get("hue"),
                    sat_before=prev.get("sat"), sat_after=state.get("sat"),
                    ct_before=prev.get("ct"), ct_after=state.get("ct"),
                    mode_at_time=current_mode,
                    trigger=trigger,
                )

    async def clear_transit_override(
        self,
        light_ids: Optional[list[str]] = None,
        transition_time: int = 30,
    ) -> None:
        """Remove transit overrides and revert the affected lights to the current mode.

        Args:
            light_ids: lights to clear. If None, clears all active transit overrides.
            transition_time: deciseconds for the revert (30 = 3s — fast-but-not-jarring).
        """
        _ = transition_time  # API-compat shim — revert uses mode-default transition speed
        if not self._st.transit_light_overrides:
            return
        if light_ids is None:
            light_ids = list(self._st.transit_light_overrides.keys())
        cleared = []
        for lid in light_ids:
            if lid in self._st.transit_light_overrides:
                del self._st.transit_light_overrides[lid]
                cleared.append(lid)
        if not cleared:
            return
        # Drop dedup cache for reverted lights so _apply_mode will actually
        # re-send the mode's state to them.
        for lid in cleared:
            self.forget_dedup_light(lid)
        # Reapply against the EFFECTIVE (override-aware) mode. Using the raw
        # `_current_mode` field here discards an active manual override and
        # snaps lights to whatever the PC activity detector last reported —
        # the bug where a brief camera flicker in a dim bedroom rendered
        # working late_night brightness right over a relax override.
        effective_mode = self._current_mode_getter()
        logger.info(
            "Transit override cleared for lights %s — reverting to mode %s",
            cleared, effective_mode,
        )
        # Re-apply the current mode's full light state. Dedup cache will no-op
        # on any lights that weren't in the transit set, so only the cleared
        # lights receive new Hue commands.
        await self._reapply_mode(effective_mode)
