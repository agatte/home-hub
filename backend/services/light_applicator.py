"""
Light applicator — GH#87 step 5 of the automation_engine decomposition.

Owns the low-level bridge-write layer: the away/external-off chokepoint,
the per-light dedup cache compare/record, the protected-light skip filter
(manual + transit overrides + sync-owned L2/L5), and the uniform/per-light
write + event-logging fan-out.

This is the bottom of the lighting pipeline. ``AutomationEngine._apply_mode``
(the policy orchestrator — scene overrides, learned overlays, multipliers,
effect reconcile) stays on the engine as coordinator and calls into here via
``apply_state``. The engine keeps thin delegates under the original method
names (``_apply_state``, ``_apply_per_light``, ``_apply_uniform``,
``_protected_light_ids``) so every existing caller and the test spies that
patch those attributes are honored unchanged.

Critic #4 (GH#87 gate): the dedup cache + override dicts live on
:class:`EngineState` and are read/written here with DIRECT O(1) dict access —
no per-light method indirection on the 0.5s poll/gather hot path. The
override manager (:class:`LightOverrideManager`) operates on the SAME
``EngineState`` dicts; this applicator only consults it for transit-prune
(``prune_expired_transit``) so expired entries don't stale-lock the skip
filter.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from backend.services.automation_constants import (
    SCREEN_SYNC_FRESH_SECONDS,
    SCREEN_SYNC_MODES,
)
from backend.services.engine_state import EngineState
from backend.services.light_override_manager import LightOverrideManager
from backend.services.light_state_calculator import ALL_LIGHT_IDS

# Same logger name as the engine so journald output is unchanged.
logger = logging.getLogger("home_hub.automation")


class LightApplicator:
    """Bridge-write layer over an EngineState: dedup, protect, fan-out, log."""

    def __init__(
        self,
        *,
        state: EngineState,
        overrides: LightOverrideManager,
        hue_getter: Callable[[], Any],
        event_logger_getter: Callable[[], Any],
        current_mode_getter: Callable[[], str],
        screen_sync_getter: Callable[[], Any],
        suppressed_getter: Callable[[], bool],
        dispatch_per_light: Callable[[dict, Optional[int]], Awaitable[None]],
        dispatch_uniform: Callable[[dict, Optional[int]], Awaitable[None]],
    ) -> None:
        self._st = state
        self._overrides = overrides
        self._hue_getter = hue_getter
        self._event_logger_getter = event_logger_getter
        self._current_mode_getter = current_mode_getter
        self._screen_sync_getter = screen_sync_getter
        # Cross-dispatch between the uniform / per-light paths routes through
        # the engine's (patchable) ``_apply_uniform`` / ``_apply_per_light``
        # delegates rather than direct self-calls, so test spies that patch
        # those engine attributes are honored from inside the apply chain —
        # the same late-bind-through-self discipline step 4 used for
        # ``reapply_mode``. Once per apply call, not per-light, so it adds no
        # hot-path dict indirection (critic #4 is about the dedup dicts).
        self._dispatch_per_light = dispatch_per_light
        self._dispatch_uniform = dispatch_uniform
        # Away/external-off chokepoint — while the apartment is suppressed NO
        # path may actuate lights (the 2026-06-10 leak: _apply_time_based and
        # scene drift call apply_state directly, and the timeout_4h clear fires
        # before the run_loop external-off continue). Paths that legitimately
        # re-light clear the flag first (signal_presence, user override).
        self._suppressed = suppressed_getter

    # ── Protected-light filter ──────────────────────────────────────────

    def protected_light_ids(self) -> set[str]:
        """Light ids the mode-apply pipeline must NOT write this tick.

        Always includes manual + transit per-light overrides. Additionally
        includes the screen-sync target lamps (L2/L5) while sync is actively
        owning them — current mode is a SCREEN_SYNC_MODE and a color was
        pushed within ``SCREEN_SYNC_FRESH_SECONDS``. Screen sync writes those
        lamps directly to the bridge (bypassing the per-light dedup cache),
        so without this guard the periodic mode-reapply — and every
        ``notify_camera_commit`` force-resend — re-writes them to their
        static state, fighting sync and producing the visible L2/L5 flicker
        (audit 2026-05-30, syncfight-1). When sync goes quiet the freshness
        gate lapses and the engine reclaims the lamps on the next tick.
        """
        protected = set(self._st.manual_light_overrides) | set(self._st.transit_light_overrides)
        sync = self._screen_sync_getter()
        if sync is not None and self._current_mode_getter() in SCREEN_SYNC_MODES:
            last = sync.last_color_at
            if last is not None:
                age = (datetime.now(timezone.utc) - last).total_seconds()
                if age < SCREEN_SYNC_FRESH_SECONDS:
                    protected |= set(sync.target_lights)
        return protected

    # ── Apply entry point ───────────────────────────────────────────────

    async def apply_state(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> None:
        """
        Apply a light state — supports both uniform and per-light formats.

        Args:
            state: Either a flat dict (applied to all lights) or a dict keyed
                   by light ID with individual states per light.
            transitiontime: Transition duration in deciseconds (10 = 1s).
                            Injected into each light command if provided.
        """
        # Away/external-off chokepoint, lower verb. _apply_mode is gated too
        # (it alone covers the scene-override + effect-reconcile actuations),
        # but _apply_time_based and scene drift call THIS verb directly —
        # and clear_override(source="timeout_4h") fires in run_loop BEFORE
        # the external-off continue, so a manual override expiring 4h into
        # an away window would re-light the empty apartment through
        # _apply_time_based (pr-review-backend block finding, 2026-06-10).
        # Paths that legitimately re-light clear the flag first.
        if self._suppressed():
            logger.debug("_apply_state skipped — away/external-off suppressed")
            return

        hue = self._hue_getter()
        if not hue or not hue.connected:
            return

        # Detect format: per-light dicts have string keys like "1", "2"
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ALL_LIGHT_IDS for k in state.keys())

        if is_per_light:
            await self._dispatch_per_light(state, transitiontime)
        else:
            await self._dispatch_uniform(state, transitiontime)

    # ── Uniform path ────────────────────────────────────────────────────

    async def apply_uniform(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> None:
        """Apply the same state to all lights (backward-compatible path)."""
        # Prune expired transit overrides before consulting them.
        self._overrides.prune_expired_transit()

        # If any lights are protected (manual / transit overrides, or sync-
        # owned L2/L5), fall through to the per-light path so the filter can
        # skip them instead of stomping them via set_all_lights.
        if self.protected_light_ids():
            per_light = {lid: state for lid in ALL_LIGHT_IDS}
            await self._dispatch_per_light(per_light, transitiontime)
            return

        hue = self._hue_getter()

        # Convert to per-light for dedup tracking
        per_light = {lid: state for lid in ALL_LIGHT_IDS}
        if per_light == self._st.last_applied_per_light:
            return

        prev_snapshot = {lid: (self._st.last_applied_per_light.get(lid) or {}).copy() for lid in ALL_LIGHT_IDS}
        self._st.last_applied_per_light = {lid: state.copy() for lid in ALL_LIGHT_IDS}
        cmd = {**state}
        if transitiontime is not None:
            cmd["transitiontime"] = transitiontime
        await hue.set_all_lights(cmd)
        logger.info(f"Applied uniform state: bri={state.get('bri')}, hue={state.get('hue')}")
        event_logger = self._event_logger_getter()
        if event_logger:
            current_mode = self._current_mode_getter()
            for lid in ALL_LIGHT_IDS:
                prev = prev_snapshot.get(lid, {})
                await event_logger.log_light_adjustment(
                    light_id=lid,
                    bri_before=prev.get("bri"), bri_after=state.get("bri"),
                    hue_before=prev.get("hue"), hue_after=state.get("hue"),
                    sat_before=prev.get("sat"), sat_after=state.get("sat"),
                    ct_before=prev.get("ct"), ct_after=state.get("ct"),
                    mode_at_time=current_mode,
                    trigger="automation",
                )

    # ── Per-light path ──────────────────────────────────────────────────

    async def apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> None:
        """Apply individual states to each light (parallel when possible)."""
        # Drop any transit overrides whose deadline has passed before we check.
        self._overrides.prune_expired_transit()

        # Filter out protected lights: manual + transit per-light overrides,
        # plus screen-sync-owned L2/L5 while sync is fresh (see
        # protected_light_ids — stops the static-vs-sync flicker).
        protected = self.protected_light_ids()
        if protected:
            skipped = [lid for lid in states if lid in protected]
            if skipped:
                states = {
                    lid: s for lid, s in states.items() if lid not in protected
                }
                logger.debug(f"Skipping overridden lights: {skipped}")
                if not states:
                    return

        # Optimization: if all lights get the same state, use the uniform path
        unique_states = list(states.values())
        if not protected and all(
            s == unique_states[0] for s in unique_states
        ):
            await self._dispatch_uniform(unique_states[0], transitiontime)
            return

        hue = self._hue_getter()

        # Build list of lights that actually changed
        tasks = []
        changed_ids = []
        # Keep the pre-change value per light so we can log accurate before/after pairs
        pre_values: dict[str, dict] = {}
        for light_id, state in states.items():
            last = self._st.last_applied_per_light.get(light_id)
            if state != last:
                pre_values[light_id] = (last or {}).copy()
                cmd = {**state}
                if transitiontime is not None:
                    cmd["transitiontime"] = transitiontime
                tasks.append(hue.set_light(light_id, cmd))
                self._st.last_applied_per_light[light_id] = state.copy()
                changed_ids.append(light_id)

        if tasks:
            await asyncio.gather(*tasks)
            on_ids = [lid for lid in changed_ids if states[lid].get("on", True)]
            off_ids = [lid for lid in changed_ids if not states[lid].get("on", True)]
            logger.info(f"Applied per-light state: on={on_ids}, off={off_ids}")
            event_logger = self._event_logger_getter()
            if event_logger:
                current_mode = self._current_mode_getter()
                for lid in changed_ids:
                    new = states[lid]
                    prev = pre_values.get(lid, {})
                    await event_logger.log_light_adjustment(
                        light_id=lid,
                        bri_before=prev.get("bri"), bri_after=new.get("bri"),
                        hue_before=prev.get("hue"), hue_after=new.get("hue"),
                        sat_before=prev.get("sat"), sat_after=new.get("sat"),
                        ct_before=prev.get("ct"), ct_after=new.get("ct"),
                        mode_at_time=current_mode,
                        trigger="automation",
                    )
