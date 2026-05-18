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
            self._record_block("camera disabled")
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
