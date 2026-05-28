"""Desk-exit kitchen brightening — kitchen comes on when Anthony leaves the desk.

When in a productive mode (working / idle / gaming / watching) during evening
or night periods, a sustained desk → absent transition raises the kitchen pair
(L3 + L4) to a time-appropriate brightness — moderate path-light in evening
(120 bri), gentle at night (60 bri). Holds until camera sees him back at the
desk, mode leaves the productive set, the user grabs an L3/L4 slider, or a 4h
failsafe expires.

Distinct from ``TransitLightingService``:
  - Scope: kitchen pair only (L3 + L4); L1 stays with transit
  - Brightness: time-of-day scaled, not flat
  - Lifetime: hold-until-return, not 10-minute auto-fade
  - Trigger window: evening / night / late_night only (skips day)

State machine:
  idle ─[mode∈productive + period∉day + camera-lost-desk ≥10s]─> active
  active ─[desk fresh again]─> idle  (revert kitchen to mode state)
  active ─[mode leaves productive set]─> idle
  active ─[period rolls to day]─> idle
  active ─[4h hard timeout]─> idle  (failsafe against wedged-absent camera)
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.services.camera_service import FACE_TRUST_THRESHOLD
from backend.services.heartbeat import HeartbeatRegistry

logger = logging.getLogger("home_hub.desk_exit_kitchen")

TZ = ZoneInfo("America/Indiana/Indianapolis")

POLL_INTERVAL_SECONDS = 2

# Sustained absence before the override fires. Matches transit's 10s — the
# desk-flap pattern (head-down typing / lean-in dropping pose+face) routinely
# fills 4–8s gaps but doesn't sustain past 10s when Anthony is actually present.
ABSENT_TRIGGER_SECONDS = 10

# Modes that imply "Anthony might be heading to the kitchen for a snack /
# water / break." Skips sleeping (lights stay off), social/relax (deliberate
# ambient palette), cooking (kitchen is already bright), gameday (own logic).
TRIGGER_MODES = frozenset({"working", "idle", "gaming", "watching"})

# Time periods where the kitchen baseline is dim enough that a leave-desk
# brighten is meaningful. Day is excluded — working/day kitchen sits at 140
# already so a bump on top is noise, not signal. late_night collapses to
# night below.
TRIGGER_PERIODS = frozenset({"evening", "night", "late_night"})

# Kitchen targets — moderate path-light in evening, gentle at night to avoid
# a 60-bri "lighthouse" effect at 1am. Pair must move together (kitchen-pair
# rule enforced by apply_desk_exit_override).
#
# CT split per lighting-curator advisory: evening tracks the working/evening
# kitchen baseline (~2778K), late-night tracks working/night L2 baseline
# (ct=370 ≈2702K) so the warm-wood + cream palette stays coherent at 1am.
# Both values clear the post-sunset cutoff (ct ≥ 333).
BRI_EVENING = 120
BRI_NIGHT = 60
KITCHEN_CT_EVENING = 360
KITCHEN_CT_NIGHT = 375

# Failsafe — much longer than transit's 10-min because "until I return" is
# the design intent. Only catches the wedged-absent camera (eg V4L2 lock
# recovered mid-frame, false-absent streak that outlasts the day).
HARD_TIMEOUT_SECONDS = 4 * 3600

# Match transit's strong-presence definition so the two services see the
# same "really there" signal — pose detection OR face above the trust
# threshold. Weak-face-only counts as absent (chair-back / picture-frame
# false positives below 0.70 conf are not Anthony).
KITCHEN_FACE_TRUST_THRESHOLD = FACE_TRUST_THRESHOLD


# ── Late-night corridor brighten ────────────────────────────────────────
#
# At late_night, a desk exit might be a kitchen trip OR a bathroom trip,
# and neither camera sees the hallway — the desktop FoV is bed+desk only,
# the Latitude is couch-only (post-2026-05-27 relocation). So we can't
# disambiguate; we fire L1 + L3/L4 together as a unified corridor that
# spills warm light into the hallway from both ends.
#
# Shorter dwell than the evening/night path (5s vs 10s) because work
# intensity at 1am is low — the desk-flap pattern that motivated the 10s
# threshold is rare in late_night idle/gaming, and a brief false-trip
# just ramps L1 softly and reverts when face returns. If false-positives
# become a nuisance over the first week, bump to 7s.

CORRIDOR_ABSENT_TRIGGER_SECONDS = 5

# L1 night-visibility threshold is bri≥45 per the apartment-layout memory.
# 80 ensures meaningful hallway spill without being jarring at 1am.
CORRIDOR_L1_BRI = 80
CORRIDOR_L1_CT = 400  # ~2500K — warm corridor-incandescent feel.

# Kitchen pair: pendants are assertive downlights — 40 is path-light
# territory, well below the cooking baseline. Same CT as the existing
# night kitchen target so transitions look coherent if the corridor
# fires and then drops back to a brighter mode.
CORRIDOR_KITCHEN_BRI = 40
CORRIDOR_KITCHEN_CT = 375

# Ramp-up stagger: L1 fires immediately, kitchen pendants follow at the
# next poll-loop tick (≈2s). Anthony reads the L1 spill first as
# "something noticed you," then the kitchen lights commit if he's
# actually heading that way.
CORRIDOR_KITCHEN_RAMP_DELAY_SECONDS = 2

# Return-to-desk debounce: face_present must be True for this many
# consecutive seconds before we trigger wind-down. Was 3s initially,
# tightened to 1s after the 2026-05-28 bathroom-trip showed face
# flicker during settle-in repeatedly reset the streak — net 9s
# perceived wind-down latency vs Transit's instant-deactivate on the
# same signal. 1s = one poll tick — still filters the single-frame
# false-positive (someone walks past the monitor) but doesn't wait
# through 3 seconds of normal sit-down jitter.
CORRIDOR_RETURN_DESK_SECONDS = 1

# Wind-down stagger: kitchen pendants fade first, L1 lingers so Anthony
# has light for the return walk through the hallway. 10s covers the
# bathroom → bedroom walk; for a kitchen trip he's already back at the
# desk by the time L1 fades.
CORRIDOR_L1_LINGER_SECONDS = 10

# Hard timeout — much tighter than desk_exit's 4h. The corridor is a
# transient state ("I'm going to the kitchen / bathroom"), not a
# hold-until-return. 10min covers even the longest realistic trip.
CORRIDOR_HARD_TIMEOUT_SECONDS = 600

# Sub-states within an active corridor.
CORRIDOR_RAMP_L1 = "ramp_l1"            # L1 just fired; kitchen not yet
CORRIDOR_HOLDING = "holding"            # Both lights up; waiting for return
CORRIDOR_WINDDOWN_KITCHEN = "winddown_kitchen"  # Kitchen fading; L1 still lit


class DeskExitKitchenService:
    """Watches camera + mode; brightens kitchen L3/L4 on sustained desk exit.

    Depends on:
      - ``AutomationEngine.apply_desk_exit_override`` / ``clear_desk_exit_override``
      - ``AutomationEngine.current_mode`` (override-aware)
      - ``AutomationEngine._get_time_period`` (day / evening / night / late_night)
      - ``AutomationEngine.is_at_desk_fresh`` (zone=desk, fresh)
      - ``CameraService.get_status`` (enabled, last_detection, detection_source, confidence)
    """

    def __init__(
        self,
        automation_engine: Any,
        camera_service: Any,
        presence_fusion: Any = None,
    ) -> None:
        self._automation = automation_engine
        self._camera = camera_service
        # Optional. ``is_at_desk_fresh`` is consulted via the engine and
        # already routes through PresenceFusion when wired, so we mostly
        # keep this for symmetry with TransitLightingService and any
        # future desktop-aware checks.
        self._presence_fusion = presence_fusion

        self._enabled: bool = True
        self._active: bool = False
        self._camera_absent_since: Optional[datetime] = None
        self._activate_ts: Optional[datetime] = None
        self._active_period: Optional[str] = None
        # Only log block-reason transitions, not every silent tick.
        self._last_block_reason: Optional[str] = None

        # Late-night corridor state — separate from the evening/night
        # kitchen-only path because the corridor manages three lights with
        # a sequenced ramp-up + wind-down, not a single override.
        self._corridor_active: bool = False
        self._corridor_substate: Optional[str] = None
        self._corridor_substate_started_at: Optional[datetime] = None
        self._corridor_activated_at: Optional[datetime] = None
        # Tracks the leading edge of a sustained face-present streak so
        # the wind-down trigger debounces against brief flickers.
        self._corridor_return_streak_start: Optional[datetime] = None

        self._heartbeat: Optional[HeartbeatRegistry] = None

    def set_heartbeat_registry(self, registry: HeartbeatRegistry) -> None:
        self._heartbeat = registry

    @property
    def active(self) -> bool:
        return self._active

    async def poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                if self._heartbeat is not None:
                    self._heartbeat.tick("desk_exit_kitchen")
                if self._enabled:
                    await self._check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("DeskExitKitchen poll error: %s", exc, exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _check(self) -> None:
        now = datetime.now(tz=TZ)
        mode = getattr(self._automation, "current_mode", "idle")
        period = self._automation._get_time_period()

        cam_status = self._camera.get_status() if self._camera else {}
        if not cam_status.get("enabled"):
            self._camera_absent_since = None
            if self._active:
                await self._deactivate("camera disabled")
            if self._corridor_active:
                await self._corridor_full_deactivate("camera disabled")
            self._record_block("camera disabled")
            return

        # ── Late-night corridor branch ──
        # At late_night with a productive mode active, route to the
        # corridor state machine (L1 + kitchen pair, sequenced). This
        # supersedes the kitchen-only path for the late_night period —
        # if we entered late_night with kitchen-only already active,
        # gracefully promote.
        if period == "late_night" and mode in TRIGGER_MODES:
            if self._active:
                await self._deactivate("promoting to corridor at late_night")
            await self._check_corridor(now, mode, cam_status)
            return

        # Rolled out of late_night (or mode left trigger set) while
        # corridor was active — wind it down through the same sequence.
        if self._corridor_active:
            if mode not in TRIGGER_MODES:
                await self._corridor_full_deactivate(
                    f"mode left trigger set (mode={mode})",
                )
            elif period != "late_night":
                # Sequenced wind-down — kitchen first, L1 lingers. The
                # period crossing isn't a hard-stop reason; let the
                # holding-state state machine handle it.
                if self._corridor_substate != CORRIDOR_WINDDOWN_KITCHEN:
                    await self._corridor_start_winddown(
                        f"period left late_night ({period})",
                    )
                else:
                    # Already winding down — let the existing tick logic
                    # finish the L1 linger.
                    await self._corridor_tick_winddown(now)
            return

        # ── If already active: look for conditions to clear ──
        if self._active:
            if mode not in TRIGGER_MODES:
                await self._deactivate(f"mode left trigger set (mode={mode})")
                return
            if period not in TRIGGER_PERIODS:
                await self._deactivate(f"period left trigger set ({period})")
                return
            if self._automation.is_at_desk_fresh():
                await self._deactivate("returned to desk")
                return
            if self._activate_ts and (
                now - self._activate_ts
            ).total_seconds() >= HARD_TIMEOUT_SECONDS:
                await self._deactivate("hard timeout")
                return
            # If the period shifted (eg evening → night) while active, repaint
            # to the new period's brightness so 9pm doesn't keep blasting 120
            # past midnight.
            target_period = "night" if period == "late_night" else period
            if target_period != self._active_period:
                await self._activate(mode, period, repaint=True)
            return

        # ── Not active: check activate conditions ──
        if mode not in TRIGGER_MODES:
            self._record_block(f"mode={mode} (not in trigger set)")
            return
        if period not in TRIGGER_PERIODS:
            self._record_block(f"period={period} (not in trigger set)")
            return

        # While Anthony is still at the desk, reset the absent timer. We use
        # the engine's freshness gate (zone=desk + fresh) rather than the raw
        # `last_detection == present` to inherit the 5-min freshness window —
        # a brief weak-face miss doesn't restart the dwell timer.
        if self._automation.is_at_desk_fresh():
            self._camera_absent_since = None
            self._record_unblock()
            return

        # Strong presence somewhere else (eg moved to bed) shouldn't trigger
        # the kitchen brighten — if he's on the bed reading, he hasn't walked
        # to the kitchen. Reset the timer when we see strong non-desk presence.
        detection = cam_status.get("last_detection", "unknown")
        src = cam_status.get("detection_source")
        conf = cam_status.get("confidence", 0.0) or 0.0
        zone = cam_status.get("zone")
        strongly_present_elsewhere = (
            detection == "present"
            and zone is not None
            and zone != "desk"
            and (src == "pose" or (src == "face" and conf >= KITCHEN_FACE_TRUST_THRESHOLD))
        )
        if strongly_present_elsewhere:
            self._camera_absent_since = None
            self._record_block(f"strong presence elsewhere (zone={zone})")
            return

        # Eligible — desk freshness expired and no strong elsewhere presence.
        # Start / advance the absent dwell.
        self._record_unblock()
        if self._camera_absent_since is None:
            self._camera_absent_since = now
            logger.info(
                "DeskExit: absent timer started (mode=%s period=%s)",
                mode, period,
            )
            return

        if (now - self._camera_absent_since).total_seconds() >= ABSENT_TRIGGER_SECONDS:
            await self._activate(mode, period)

    # ── Corridor state machine ──────────────────────────────────────────

    async def _check_corridor(
        self, now: datetime, mode: str, cam_status: dict,
    ) -> None:
        """Late-night corridor: L1 + kitchen pair, sequenced ramp + fade.

        Called from ``_check`` when period == late_night and mode is in
        the trigger set. Handles both arming (sustained desk-absence
        builds toward activation) and the active state machine.
        """
        # If already active, advance the state machine.
        if self._corridor_active:
            await self._tick_corridor_active(now, mode, cam_status)
            return

        # Arming phase — same shape as the kitchen-only path but with
        # the corridor-specific dwell threshold.
        if self._automation.is_at_desk_fresh():
            self._camera_absent_since = None
            self._record_unblock()
            return

        # Strong presence elsewhere (couch, hypothetical future zones)
        # means Anthony didn't head to the kitchen/bathroom — defer.
        detection = cam_status.get("last_detection", "unknown")
        src = cam_status.get("detection_source")
        conf = cam_status.get("confidence", 0.0) or 0.0
        zone = cam_status.get("zone")
        strongly_present_elsewhere = (
            detection == "present"
            and zone is not None
            and zone != "desk"
            and (src == "pose" or (src == "face" and conf >= KITCHEN_FACE_TRUST_THRESHOLD))
        )
        if strongly_present_elsewhere:
            self._camera_absent_since = None
            self._record_block(f"corridor: strong presence elsewhere (zone={zone})")
            return

        self._record_unblock()
        if self._camera_absent_since is None:
            self._camera_absent_since = now
            logger.info(
                "Corridor: absent timer started (mode=%s)", mode,
            )
            return

        if (now - self._camera_absent_since).total_seconds() >= CORRIDOR_ABSENT_TRIGGER_SECONDS:
            await self._activate_corridor(mode)

    async def _tick_corridor_active(
        self, now: datetime, mode: str, cam_status: dict,
    ) -> None:
        """Advance an in-flight corridor through its substates."""
        # Hard-timeout failsafe — independent of state machine.
        if (
            self._corridor_activated_at is not None
            and (now - self._corridor_activated_at).total_seconds()
            >= CORRIDOR_HARD_TIMEOUT_SECONDS
        ):
            if self._corridor_substate != CORRIDOR_WINDDOWN_KITCHEN:
                await self._corridor_start_winddown("hard timeout")
            else:
                await self._corridor_tick_winddown(now)
            return

        # Substate transitions
        if self._corridor_substate == CORRIDOR_RAMP_L1:
            # L1 just lit; arm the kitchen pair after the stagger delay.
            elapsed = (now - (self._corridor_substate_started_at or now)).total_seconds()
            if elapsed >= CORRIDOR_KITCHEN_RAMP_DELAY_SECONDS:
                await self._corridor_ramp_kitchen(now)
            return

        if self._corridor_substate == CORRIDOR_HOLDING:
            # Both lights up — look for return-to-desk to begin wind-down.
            if self._automation.is_at_desk_fresh():
                if self._corridor_return_streak_start is None:
                    self._corridor_return_streak_start = now
                elif (
                    now - self._corridor_return_streak_start
                ).total_seconds() >= CORRIDOR_RETURN_DESK_SECONDS:
                    await self._corridor_start_winddown("returned to desk")
            else:
                self._corridor_return_streak_start = None
            return

        if self._corridor_substate == CORRIDOR_WINDDOWN_KITCHEN:
            await self._corridor_tick_winddown(now)
            return

    async def _activate_corridor(self, mode: str) -> None:
        """Fire L1 — Phase 1 of the ramp-up. Kitchen follows on next tick."""
        states = {
            "1": {"on": True, "bri": CORRIDOR_L1_BRI, "ct": CORRIDOR_L1_CT},
        }
        await self._automation.apply_corridor_override(
            states,
            duration_seconds=CORRIDOR_HARD_TIMEOUT_SECONDS,
            transition_time=15,
        )
        now = datetime.now(tz=TZ)
        self._corridor_active = True
        self._corridor_substate = CORRIDOR_RAMP_L1
        self._corridor_substate_started_at = now
        self._corridor_activated_at = now
        self._corridor_return_streak_start = None
        self._camera_absent_since = None
        logger.info(
            "Corridor activated (mode=%s) — L1 ramping; kitchen in %ds",
            mode, CORRIDOR_KITCHEN_RAMP_DELAY_SECONDS,
        )

    async def _corridor_ramp_kitchen(self, now: datetime) -> None:
        """Phase 2 of ramp-up — bring up the kitchen pair to path-light."""
        kitchen = {"on": True, "bri": CORRIDOR_KITCHEN_BRI, "ct": CORRIDOR_KITCHEN_CT}
        states = {"3": dict(kitchen), "4": dict(kitchen)}
        await self._automation.apply_corridor_override(
            states,
            duration_seconds=CORRIDOR_HARD_TIMEOUT_SECONDS,
            transition_time=15,
        )
        self._corridor_substate = CORRIDOR_HOLDING
        self._corridor_substate_started_at = now
        logger.info("Corridor: kitchen pair ramped (bri=%d)", CORRIDOR_KITCHEN_BRI)

    async def _corridor_start_winddown(self, reason: str) -> None:
        """Begin sequenced wind-down — kitchen first, L1 lingers."""
        await self._automation.clear_corridor_override(
            light_ids=["3", "4"], transition_time=30,
        )
        now = datetime.now(tz=TZ)
        self._corridor_substate = CORRIDOR_WINDDOWN_KITCHEN
        self._corridor_substate_started_at = now
        logger.info(
            "Corridor: wind-down started (%s) — kitchen fading; L1 lingers %ds",
            reason, CORRIDOR_L1_LINGER_SECONDS,
        )

    async def _corridor_tick_winddown(self, now: datetime) -> None:
        """Tail end of wind-down — clear L1 once the linger window expires."""
        elapsed = (now - (self._corridor_substate_started_at or now)).total_seconds()
        if elapsed < CORRIDOR_L1_LINGER_SECONDS:
            return
        await self._automation.clear_corridor_override(
            light_ids=["1"], transition_time=30,
        )
        logger.info("Corridor: L1 cleared — deactivated")
        self._corridor_reset_state()

    async def _corridor_full_deactivate(self, reason: str) -> None:
        """Hard-stop the corridor — used on camera disable / mode exit.

        Skips the sequenced fade because the trigger condition (camera
        gone, mode left trigger set) means we want lights back to the
        current mode now, not after a 10s linger.
        """
        if not self._corridor_active:
            return
        await self._automation.clear_corridor_override(
            light_ids=["1", "3", "4"], transition_time=30,
        )
        logger.info("Corridor: full deactivate (%s)", reason)
        self._corridor_reset_state()

    def _corridor_reset_state(self) -> None:
        self._corridor_active = False
        self._corridor_substate = None
        self._corridor_substate_started_at = None
        self._corridor_activated_at = None
        self._corridor_return_streak_start = None

    def _record_block(self, reason: str) -> None:
        if reason != self._last_block_reason:
            logger.info("DeskExit: blocked (%s)", reason)
            self._last_block_reason = reason
            self._camera_absent_since = None

    def _record_unblock(self) -> None:
        if self._last_block_reason is not None:
            logger.info("DeskExit: unblocked (was %s)", self._last_block_reason)
            self._last_block_reason = None

    def _kitchen_states(self, period: str) -> dict[str, dict]:
        if period == "evening":
            bri, ct = BRI_EVENING, KITCHEN_CT_EVENING
        else:
            bri, ct = BRI_NIGHT, KITCHEN_CT_NIGHT
        kitchen = {"on": True, "bri": bri, "ct": ct}
        return {"3": dict(kitchen), "4": dict(kitchen)}

    async def _activate(self, mode: str, period: str, *, repaint: bool = False) -> None:
        target_period = "night" if period == "late_night" else period
        states = self._kitchen_states(target_period)
        await self._automation.apply_desk_exit_override(
            states,
            duration_seconds=HARD_TIMEOUT_SECONDS,
            transition_time=5,
        )
        self._active = True
        if not repaint:
            self._activate_ts = datetime.now(tz=TZ)
        self._active_period = target_period
        logger.info(
            "DeskExit %s (mode=%s period=%s bri=%d)",
            "repainted" if repaint else "activated",
            mode, target_period, states["3"]["bri"],
        )

    async def _deactivate(self, reason: str) -> None:
        if not self._active:
            return
        await self._automation.clear_desk_exit_override(transition_time=20)
        self._active = False
        self._camera_absent_since = None
        self._activate_ts = None
        self._active_period = None
        logger.info("DeskExit deactivated (%s)", reason)

    async def close(self) -> None:
        if self._active:
            await self._deactivate("service shutdown")
        if self._corridor_active:
            await self._corridor_full_deactivate("service shutdown")
