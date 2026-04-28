"""Transit lighting — briefly brighten the navigation path when Anthony steps
out of the bedroom.

When the camera loses him (working / gaming / watching / relax modes where the
kitchen and living room are dim or off), briefly raise L1 / L3 / L4 to a gentle
"I can see where I'm going" level so he doesn't have to manually switch modes
or turn lights on. L2 is untouched — the bedroom bias lamp stays on the
current mode's state for when he sits back down.

State machine:
  idle ─[camera absent ≥4s + eligible mode + non-stationary zone]─> active
  active ─[camera present ≥2s]─> idle  (revert lights)
  active ─[mode left trigger set: sleeping/cooking/social/idle]─> idle
  active ─[10-minute hard timeout]─> idle  (failsafe)

Eligible mode means the *effective* mode (override-aware) is in
TRIGGER_MODES — so a manual relax/working/gaming/watching override
still lets transit fire. sleeping/cooking/social overrides naturally
fall outside TRIGGER_MODES and block, preserving "I want it dark /
specifically lit" intent.

The 10-min hard timeout is the only protection against runaway if the
camera mis-fires (e.g. wedged "absent" forever). Phone-presence used to
be a secondary safety net but was removed when home/away was retired.

Runs inside the FastAPI process; poll loop wakes every 2s to align with camera.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.transit_lighting")

TZ = ZoneInfo("America/Indiana/Indianapolis")

# Poll cadence — matches the camera's 2s polling so we react promptly.
POLL_INTERVAL_SECONDS = 2

# How long camera must report "absent" before we consider Anthony in transit.
# Tightened from 10s → 4s (2026-04-26) after the bedroom→kitchen walk felt
# slow in practice. 4s still debounces a brief head-turn or 2s of typing
# out-of-frame, but lets transit fire ~6-8s sooner. Camera's own 15-frame
# absent threshold (~30s) is much longer, so transit lights up well before
# the camera lane decides Anthony has gone idle.
ABSENT_TRIGGER_SECONDS = 4

# How long camera must report "present" before we revert — protects against
# a one-frame false positive flipping the lights back too eagerly.
PRESENT_CLEAR_SECONDS = 2

# Failsafe: if we never see him return, drop the override after this long.
# Matches the deadline passed to ``apply_transit_override``.
HARD_TIMEOUT_SECONDS = 600

# Modes where kitchen / living room are dim or off and transit lighting is
# worth firing. Intentionally conservative — cooking is already bright, social
# has a medium palette, sleeping wants to stay dark, gameday is handled
# elsewhere.
TRIGGER_MODES = frozenset({"working", "gaming", "watching", "relax"})

# Zones where transit lighting must NOT fire — Anthony is stationary, not
# transiting. The bed zone is the painful one: face / pose detection flickers
# wildly under blankets in low light (consecutive frames swing 0.0 → 0.99 →
# 0.0 confidence), and absent each glitch would otherwise raise L1 + L3 + L4
# every few seconds. Gate is on the *committed* zone reading (15s hysteresis
# inside camera_service), so brief absences don't drop the gate either.
STATIONARY_ZONES = frozenset({"bed"})

# Late-night adjustment — don't blind him if it's past 23:00 or before 06:00.
LATE_NIGHT_START_HOUR = 23
LATE_NIGHT_END_HOUR = 6


class TransitLightingService:
    """Watches camera + mode state; activates transit lighting.

    Depends on:
      - ``AutomationEngine.apply_transit_override`` / ``clear_transit_override``
      - ``CameraService.get_status`` (reads ``last_detection``, ``enabled``)
    """

    def __init__(
        self,
        automation_engine: Any,
        camera_service: Any,
    ) -> None:
        self._automation = automation_engine
        self._camera = camera_service

        self._enabled: bool = True
        self._active: bool = False
        self._camera_absent_since: Optional[datetime] = None
        # Flap-suppression for the activate path: once the absent timer is
        # running, single-frame "present" detections (often pose extrapolating
        # a partial body as Anthony exits frame) shouldn't reset it. We
        # require PRESENT_CLEAR_SECONDS of sustained presence to confirm a
        # real return before clearing the absent timer.
        self._presence_during_absent_since: Optional[datetime] = None
        self._camera_present_since: Optional[datetime] = None
        self._transit_start: Optional[datetime] = None
        # Last reason the activate path bailed early. Only the *first* tick
        # of a new block reason emits an INFO log; subsequent ticks with the
        # same reason stay quiet to avoid spamming. None means "currently
        # eligible to fire (or already firing)."
        self._last_block_reason: Optional[str] = None
        self._heartbeat = None  # HeartbeatRegistry, set via set_heartbeat_registry

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    @property
    def active(self) -> bool:
        """Whether transit lighting is currently applying an override."""
        return self._active

    async def poll_loop(self) -> None:
        """Background task — evaluate the trigger state every POLL_INTERVAL_SECONDS."""
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                if self._heartbeat is not None:
                    self._heartbeat.tick("transit_lighting")
                if self._enabled:
                    await self._check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("TransitLighting poll error: %s", exc, exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _check(self) -> None:
        """One tick of the state machine — may activate or deactivate."""
        now = datetime.now(tz=TZ)

        # Use the override-aware mode so a manual relax / working / gaming /
        # watching override still lets transit fire when Anthony leaves the
        # bedroom (e.g. winddown sets relax at 22:00 — kitchen still needs
        # transit lighting). sleeping / cooking / social overrides naturally
        # fall outside TRIGGER_MODES and continue to block.
        mode = getattr(self._automation, "current_mode", "idle")

        # Camera may be disabled (opt-in); bail if no camera signal available.
        cam_status = self._camera.get_status() if self._camera else {}
        if not cam_status.get("enabled"):
            # Reset any trigger timer so we don't fire the moment the camera
            # comes back online.
            self._camera_absent_since = None
            self._presence_during_absent_since = None
            if self._active:
                await self._deactivate("camera disabled")
            self._record_block("camera disabled")
            return

        detection = cam_status.get("last_detection", "unknown")
        zone = cam_status.get("zone")

        # ── If already active: look for conditions to clear ──
        if self._active:
            # Effective mode out of the trigger set (sleeping, cooking, social,
            # idle) → revert. Manual overrides to a trigger mode are fine.
            if mode not in TRIGGER_MODES:
                await self._deactivate(f"mode exited trigger set (mode={mode})")
                return

            # Camera now sees him in a stationary zone (bed) — he didn't walk
            # to the kitchen, he sat back down. Revert immediately so the
            # transit lift doesn't linger after he's clearly settled.
            if zone in STATIONARY_ZONES:
                await self._deactivate(f"zone={zone} (user stationary)")
                return

            # Hard timeout — belt-and-suspenders against stuck state
            if self._transit_start and (now - self._transit_start).total_seconds() >= HARD_TIMEOUT_SECONDS:
                await self._deactivate("hard timeout")
                return

            # Camera sees him again — revert after brief dwell
            if detection == "present":
                if self._camera_present_since is None:
                    self._camera_present_since = now
                elif (now - self._camera_present_since).total_seconds() >= PRESENT_CLEAR_SECONDS:
                    await self._deactivate("camera returned")
                    return
            else:
                self._camera_present_since = None
            return

        # ── Not active: look for conditions to activate ──
        if mode not in TRIGGER_MODES:
            self._record_block(f"mode={mode} (not in trigger set)")
            return
        # Last committed zone is "bed" → he's reclined in the bedroom. Camera
        # absences in this state are detection flicker (face/pose tossing
        # under blankets in low light), not navigation. Block before the
        # absent-dwell timer accumulates so a flap-storm can't fire transit.
        if zone in STATIONARY_ZONES:
            self._record_block(f"zone={zone} (user stationary)")
            return

        # All gates clear — log the unblock so journalctl shows when the
        # service became eligible again.
        self._record_unblock()

        if detection != "absent":
            if self._camera_absent_since is None:
                # Not currently waiting on the absent dwell — nothing to debounce.
                self._presence_during_absent_since = None
                return
            # Already mid-dwell: a single "present" frame might be MediaPipe pose
            # extrapolating a partial body. Require PRESENT_CLEAR_SECONDS of
            # sustained presence before treating it as a true return.
            if self._presence_during_absent_since is None:
                self._presence_during_absent_since = now
                return
            if (now - self._presence_during_absent_since).total_seconds() >= PRESENT_CLEAR_SECONDS:
                logger.info(
                    "Transit: absent timer reset (sustained present for %ss)",
                    PRESENT_CLEAR_SECONDS,
                )
                self._camera_absent_since = None
                self._presence_during_absent_since = None
            # Else: still inside flap window — keep the absent timer running.
            return

        # Detection is absent — clear flap tracking and advance the dwell.
        self._presence_during_absent_since = None
        if self._camera_absent_since is None:
            self._camera_absent_since = now
            logger.info(
                "Transit: absent timer started (mode=%s)", mode,
            )
            return

        if (now - self._camera_absent_since).total_seconds() >= ABSENT_TRIGGER_SECONDS:
            await self._activate(mode)

    def _record_block(self, reason: str) -> None:
        """Note that the activate path bailed; log only on reason transitions.

        Also clears any pending absent dwell so a stale timer doesn't fire
        the instant the block lifts (e.g. mode flips away → working after
        the user has been gone for minutes).
        """
        if reason != self._last_block_reason:
            logger.info("Transit: blocked (%s)", reason)
            self._last_block_reason = reason
            self._camera_absent_since = None
            self._presence_during_absent_since = None

    def _record_unblock(self) -> None:
        """Log when the activate path's gates clear after having been blocked."""
        if self._last_block_reason is not None:
            logger.info(
                "Transit: unblocked (was %s)", self._last_block_reason,
            )
            self._last_block_reason = None

    def _navigation_states(self) -> dict[str, dict]:
        """Per-light targets for transit. Lower at late-night to avoid glare."""
        hour = datetime.now(tz=TZ).hour
        late_night = hour >= LATE_NIGHT_START_HOUR or hour < LATE_NIGHT_END_HOUR

        if late_night:
            living_room = {"on": True, "bri": 60, "ct": 400}
            kitchen = {"on": True, "bri": 40, "ct": 400}
        else:
            living_room = {"on": True, "bri": 120, "ct": 360}
            kitchen = {"on": True, "bri": 80, "ct": 360}

        # L1 = living room, L3 = kitchen front, L4 = kitchen back. L2 (bedroom
        # bias) is left on the current mode's state so walking back into the
        # bedroom feels continuous.
        return {"1": living_room, "3": kitchen, "4": kitchen}

    async def _activate(self, mode: str) -> None:
        states = self._navigation_states()
        # Fast 0.5s "snap on" rather than a 2s ramp — when stepping into a
        # dark room you want lights *now*, not a slow fade-in.
        await self._automation.apply_transit_override(
            states,
            duration_seconds=HARD_TIMEOUT_SECONDS,
            transition_time=5,
        )
        self._active = True
        self._transit_start = datetime.now(tz=TZ)
        self._camera_present_since = None
        self._presence_during_absent_since = None
        logger.info(
            "Transit lighting activated (mode=%s, lights=%s)",
            mode, list(states.keys()),
        )

    async def _deactivate(self, reason: str) -> None:
        if not self._active:
            return
        await self._automation.clear_transit_override(transition_time=30)
        self._active = False
        self._camera_absent_since = None
        self._camera_present_since = None
        self._presence_during_absent_since = None
        self._transit_start = None
        logger.info("Transit lighting deactivated (%s)", reason)

    async def close(self) -> None:
        """Shutdown hook — release any active override so lights revert cleanly."""
        if self._active:
            await self._deactivate("service shutdown")
