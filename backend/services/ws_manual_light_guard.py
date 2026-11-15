"""Fail-closed manual WebSocket light dispatch under the existing Hue boundary.

This is the backend writer used by the legacy Svelte LightCard route, not a
new Quiet Atlas actuator. An acknowledgement is a Hue transport ACK, never
physical confirmation. No production activation is authorized by this module.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from backend.services.light_state_calculator import ALL_LIGHT_IDS
from backend.services.lighting_transition_boundary import settle_lighting_io

logger = logging.getLogger(__name__)


_COMMAND_FIELDS = frozenset({"on", "bri", "hue", "sat", "ct"})
_ALLOWED_FIELDS = _COMMAND_FIELDS | {"transitiontime"}
_AWAKE_HOUSE_STATES = frozenset({"home", "winding_down"})


@dataclass(frozen=True)
class ManualLightDispatch:
    status: str  # denied / unavailable / uncertain / acknowledged
    before: dict[str, Any] | None = None


def _valid_request(light_id: str, state: dict[str, Any]) -> bool:
    """The WS Pydantic schema validates ranges/types before calling here."""
    if not (
        type(light_id) is str
        and light_id in ALL_LIGHT_IDS
        and type(state) is dict
        and bool(_COMMAND_FIELDS & state.keys())
        and set(state) <= _ALLOWED_FIELDS
        and not ("ct" in state and ("hue" in state or "sat" in state))
    ):
        return False
    bounds = {"bri": (1, 254), "hue": (0, 65535), "sat": (0, 254),
              "ct": (153, 500), "transitiontime": (0, 600)}
    for key, value in state.items():
        if key == "on":
            if type(value) is not bool:
                return False
        elif type(value) is not int or not bounds[key][0] <= value <= bounds[key][1]:
            return False
    return True


async def dispatch_manual_light(engine, hue, light_id: str, state: dict[str, Any]) -> ManualLightDispatch:
    """Issue a scoped authority lease before queuing, then revalidate at Hue dispatch.

    No trust or takeover authority comes from the WebSocket client, REST
    readings, or the lease itself. Stronger owners always win. Existing manual
    ownership may be adjusted again, but not when ScreenSync/transit/scene or
    a protected owner also owns the fixture.

    A shielded transaction keeps the boundary held through the bridge ACK and
    persistence even if the browser disconnects. Rejected/preflight requests
    never stamp ownership. Ambiguous Hue results are never retried.
    """
    if not _valid_request(light_id, state):
        return ManualLightDispatch("denied")
    if engine is None or hue is None:
        return ManualLightDispatch("unavailable")
    boundary = getattr(engine, "lighting_transition_boundary", None)
    if (
        boundary is None
        or getattr(hue, "_transition_boundary", None) is not boundary
        or not getattr(hue, "connected", False)
    ):
        return ManualLightDispatch("unavailable")

    # Mint before the wait; a queued command cannot renew away a newer owner.
    lease = boundary.authority.issue("websocket_manual", [light_id])

    def permitted(candidate_lease) -> bool:
        try:
            return bool(
                hue.connected
                and engine.house_state in _AWAKE_HOUSE_STATES
                and engine.validate_lighting_lease(candidate_lease, allow_manual=True)
            )
        except Exception:
            # Missing/uncertain owner or lifecycle evidence must fail closed.
            return False

    def allowed() -> bool:
        return permitted(lease)

    # For the HueService loop/worker rendezvous, bind the original immutable
    # lease to the final raw-generation snapshot as well as the policy check.
    allowed.dispatch_lease = lease

    def forget_uncertain() -> None:
        # An unacknowledged bridge command may still have changed the bulb.
        # Drop stale dedup state, without taking ownership from ScreenSync.
        try:
            engine.forget_ambiguous_light_write(
                [light_id], preserve_screen_sync=True,
            )
        except Exception:
            # The physical result is already uncertain. A broken cache
            # reconciler must not surface a generic retryable exception.
            logger.exception("Unable to invalidate uncertain light cache")

    async def transaction() -> ManualLightDispatch:
        async with boundary.serialized():
            if not allowed():
                return ManualLightDispatch("denied")
            try:
                before = await hue.get_light(light_id)
            except Exception:
                return ManualLightDispatch("unavailable")
            if (
                type(before) is not dict
                or before.get("light_id") != light_id
                or before.get("reachable") is not True
            ):
                return ManualLightDispatch("unavailable")
            if not allowed():
                return ManualLightDispatch("denied")
            try:
                ack = await boundary.run_write(
                    lambda: hue.set_light(light_id, state),
                    validator=allowed,
                    light_ids=[light_id],
                )
            except Exception:
                # Even exceptions might follow a partial Hue bridge mutation.
                forget_uncertain()
                return ManualLightDispatch("uncertain")
            if ack is not True:
                forget_uncertain()
                return ManualLightDispatch("uncertain")
            # A stronger owner can arrive during the physical bridge call.
            # Never stamp manual over an owner that superseded this request.
            if not allowed():
                forget_uncertain()
                return ManualLightDispatch("uncertain")
            # A valid Hue ACK is not physical completion. Publishing our manual
            # stamp invalidates the original lease; issue a fresh evidence
            # checkpoint only AFTER the stamp to detect later owner takeover.
            try:
                engine.mark_light_manual(light_id, state)
                # Marking first retains the existing target base. The later
                # canonical leased-write record evicts stale automation dedup
                # so a mode reconciliation after manual expiry cannot skip.
                engine.record_leased_light_write(
                    light_id, state, supersede_screen_sync=False,
                )
                stamped_lease = boundary.authority.issue(
                    "websocket_manual_ack", [light_id],
                )
                await engine.persist_manual_light_ownership(raise_on_error=True)
            except Exception:
                # The Hue outcome is already acknowledged, but manual
                # durability cannot be asserted; never retry it automatically.
                return ManualLightDispatch("uncertain")
            if not permitted(stamped_lease):
                return ManualLightDispatch("uncertain")
            return ManualLightDispatch("acknowledged", before=before)

    # settle_lighting_io shields and drains the entire transaction on browser
    # cancellation. Do not release the lock while an acknowledged physical
    # write is still awaiting ownership persistence.
    return await settle_lighting_io(transaction())
