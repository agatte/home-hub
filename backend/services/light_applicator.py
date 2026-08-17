"""
Light applicator — GH#87 step 5 of the automation_engine decomposition.

Owns the low-level bridge-write layer: the away/external-off chokepoint,
the per-light dedup cache compare/record, the protected-light skip filter
(manual + transit overrides + fresh screen-sync-owned lights), and the uniform/per-light
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
from dataclasses import dataclass, field
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


@dataclass
class LightApplyResult:
    """Per-light outcome of one bridge application."""

    successful: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    deduplicated: set[str] = field(default_factory=set)

    def covers(self, required: set[str]) -> bool:
        """True only when every required light received a successful write."""
        return required <= self.successful


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
        dispatch_per_light: Callable[
            [dict, Optional[int]], Awaitable[LightApplyResult]
        ],
        dispatch_uniform: Callable[
            [dict, Optional[int]], Awaitable[LightApplyResult]
        ],
        transition_boundary,
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
        self._transition_boundary = transition_boundary
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
        includes the screen-sync lamps with fresh per-light ownership while sync is actively
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
            fresh_owned = getattr(sync, "fresh_owned_light_ids", None)
            if callable(fresh_owned):
                protected |= set(fresh_owned())
            else:
                # Compatibility for older stubs: legacy screen-sync exposed
                # only one global freshness stamp plus its target list.
                last = sync.last_color_at
                if last is not None:
                    age = (datetime.now(timezone.utc) - last).total_seconds()
                    if age < SCREEN_SYNC_FRESH_SECONDS:
                        protected |= set(sync.target_lights)
        return protected

    # ── Apply entry point ───────────────────────────────────────────────

    def _invalidate_screen_sync_cache(self, light_ids: list[str]) -> None:
        """Mark normal-automation bridge writes unknown to screen sync."""
        sync = self._screen_sync_getter()
        invalidate = getattr(sync, "invalidate_sent_state", None)
        if invalidate is not None:
            invalidate(light_ids)

    async def apply_state(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> LightApplyResult:
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
            return LightApplyResult(skipped=set(ALL_LIGHT_IDS))

        hue = self._hue_getter()
        if not hue or not hue.connected:
            return LightApplyResult(failed=set(ALL_LIGHT_IDS))

        # Detect format: per-light dicts have string keys like "1", "2"
        is_per_light = all(
            isinstance(v, dict) for v in state.values()
        ) and any(k in ALL_LIGHT_IDS for k in state.keys())

        if is_per_light:
            return await self._dispatch_per_light(state, transitiontime)
        return await self._dispatch_uniform(state, transitiontime)

    # ── Uniform path ────────────────────────────────────────────────────

    async def apply_uniform(
        self, state: dict[str, Any], transitiontime: int | None = None,
    ) -> LightApplyResult:
        """Apply the same state to all lights (backward-compatible path)."""
        # Prune expired transit overrides before consulting them.
        self._overrides.prune_expired_transit()

        # Always fan out per-light. A bridge-wide boolean cannot reveal mixed
        # acknowledgement results, so it cannot safely advance an independent
        # per-light dedup cache.
        per_light = {lid: state for lid in ALL_LIGHT_IDS}
        return await self._dispatch_per_light(per_light, transitiontime)

    # ── Per-light path ──────────────────────────────────────────────────

    async def apply_per_light(
        self, states: dict[str, dict], transitiontime: int | None = None,
    ) -> LightApplyResult:
        """Apply individual states to each light (parallel when possible)."""
        if not self._transition_boundary.held_by_current_task:
            async with self._transition_boundary.serialized():
                result, log_entries = await self._apply_per_light_locked(
                    states, transitiontime,
                )
            await self._log_successful_writes(log_entries)
            return result

        result, log_entries = await self._apply_per_light_locked(
            states, transitiontime,
        )
        await self._log_successful_writes(log_entries)
        return result

    async def _apply_per_light_locked(
        self, states: dict[str, dict], transitiontime: int | None,
    ) -> tuple[LightApplyResult, list[tuple[str, dict, dict]]]:
        """Bridge/cache portion of per-light apply; boundary must be held."""
        if self._suppressed():
            return (
                LightApplyResult(skipped=set(states)),
                [],
            )

        # Drop any transit overrides whose deadline has passed before we check.
        self._overrides.prune_expired_transit()

        # Filter out protected lights: manual + transit per-light overrides,
        # plus screen-fresh screen-sync-owned lights while sync is fresh (see
        # protected_light_ids — stops the static-vs-sync flicker).
        protected = self.protected_light_ids()
        skipped: set[str] = set()
        if protected:
            skipped = {lid for lid in states if lid in protected}
            if skipped:
                states = {
                    lid: s for lid, s in states.items() if lid not in protected
                }
                logger.debug("Skipping overridden lights: %s", sorted(skipped))
                if not states:
                    return LightApplyResult(skipped=skipped), []

        hue = self._hue_getter()

        # Build list of lights that actually changed
        tasks = []
        changed_ids = []
        deduplicated: set[str] = set()
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
                changed_ids.append(light_id)
            else:
                deduplicated.add(light_id)

        successful_ids: list[str] = []
        failed_ids: list[str] = []
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful_ids = [
                light_id
                for light_id, result in zip(changed_ids, results)
                if result is True
            ]
            failed_ids = [
                light_id
                for light_id, result in zip(changed_ids, results)
                if result is not True
            ]
            for light_id in successful_ids:
                self._st.last_applied_per_light[light_id] = states[light_id].copy()
            if successful_ids:
                self._invalidate_screen_sync_cache(successful_ids)
            on_ids = [lid for lid in successful_ids if states[lid].get("on", True)]
            off_ids = [lid for lid in successful_ids if not states[lid].get("on", True)]
            logger.info(
                "Applied per-light state: success=%s failed=%s skipped=%s on=%s off=%s",
                successful_ids, failed_ids, sorted(skipped), on_ids, off_ids,
            )
        log_entries = [
            (light_id, pre_values.get(light_id, {}), states[light_id])
            for light_id in successful_ids
        ]
        return (
            LightApplyResult(
                successful=set(successful_ids),
                failed=set(failed_ids),
                skipped=skipped,
                deduplicated=deduplicated,
            ),
            log_entries,
        )

    async def _log_successful_writes(
        self, entries: list[tuple[str, dict, dict]],
    ) -> None:
        """Log acknowledged adjustments outside the Hue serialization lock."""
        event_logger = self._event_logger_getter()
        if not event_logger:
            return
        current_mode = self._current_mode_getter()
        for light_id, previous, new in entries:
            await event_logger.log_light_adjustment(
                light_id=light_id,
                bri_before=previous.get("bri"), bri_after=new.get("bri"),
                hue_before=previous.get("hue"), hue_after=new.get("hue"),
                sat_before=previous.get("sat"), sat_after=new.get("sat"),
                ct_before=previous.get("ct"), ct_after=new.get("ct"),
                mode_at_time=current_mode,
                trigger="automation",
            )

    async def establish_effect_release(
        self,
        intended_states: dict[str, dict] | None,
        transitiontime: int | None,
        release_light_ids: set[str],
    ) -> LightApplyResult:
        """Force safe targets onto every light before an effect is released.

        Protected lamps are deliberately written, but with their authoritative
        held target rather than the incoming mode target. Ownership stamps are
        read only and remain intact.
        """
        if not self._transition_boundary.held_by_current_task:
            raise RuntimeError("Effect safety establishment requires the boundary")

        self._overrides.prune_expired_transit()
        protected = self.protected_light_ids()
        sync = self._screen_sync_getter()
        targets: dict[str, dict] = {}
        unresolved: set[str] = set()
        sync_authoritative: set[str] = set()

        for light_id in release_light_ids:
            target: dict | None = None
            if light_id in protected:
                target = self._st.transit_light_targets.get(light_id)
                if target is None:
                    target = self._st.manual_light_targets.get(light_id)
            if target is None and sync is not None:
                getter = getattr(sync, "fresh_authoritative_state", None)
                if getter is not None:
                    target = getter(light_id)
                    if target is not None:
                        sync_authoritative.add(light_id)
            if target is None and intended_states is not None:
                target = intended_states.get(light_id)
            if target is None:
                target = self._st.last_applied_per_light.get(light_id)
            if target is None:
                unresolved.add(light_id)
            else:
                targets[light_id] = target.copy()

        if unresolved:
            logger.warning(
                "Effect release safety unresolved: lights=%s protected=%s",
                sorted(unresolved), sorted(protected & unresolved),
            )

        hue = self._hue_getter()
        if hue is None or not hue.connected:
            logger.warning(
                "Effect release safety unavailable: Hue v1 service disconnected"
            )
            return LightApplyResult(failed=set(release_light_ids))
        changed_ids = list(targets)
        tasks = []
        for light_id in changed_ids:
            cmd = targets[light_id].copy()
            if transitiontime is not None:
                cmd["transitiontime"] = transitiontime
            tasks.append(hue.set_light(light_id, cmd))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = {
            light_id
            for light_id, result in zip(changed_ids, results)
            if result is True
        }
        failed = release_light_ids - successful
        for light_id in successful:
            self._st.last_applied_per_light[light_id] = targets[light_id].copy()
        invalidated = successful - sync_authoritative
        if invalidated:
            self._invalidate_screen_sync_cache(sorted(invalidated))
        logger.info(
            "Effect release safety writes: success=%s failed=%s protected=%s",
            sorted(successful), sorted(failed), sorted(protected & release_light_ids),
        )
        return LightApplyResult(
            successful=successful,
            failed=failed - unresolved,
            skipped=unresolved,
        )
