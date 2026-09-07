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
from backend.services.light_state_calculator import path_light_brightness

logger = logging.getLogger("home_hub.desk_exit_kitchen")

TZ = ZoneInfo("America/Indiana/Indianapolis")

POLL_INTERVAL_SECONDS = 2

# Sustained absence before the override fires. Matches transit's 10s — the
# desk-flap pattern (head-down typing / lean-in dropping pose+face) routinely
# fills 4–8s gaps but doesn't sustain past 10s when Anthony is actually present.
ABSENT_TRIGGER_SECONDS = 10

# Return-to-desk debounce on the evening/night kitchen-only path. The override
# must see is_at_desk_fresh() True across this streak before it deactivates —
# WITHOUT this the path deactivated on the FIRST True frame, and since the
# desktop pc_agent's face_present signal is last-write-wins with no debounce
# (a single missed/low-confidence frame flips it false→true around the trust
# threshold during gaming), a lone recovered frame released the kitchen, the
# mode-apply loop repainted the gaming palette, then a real ≥10s gap re-armed
# and re-fired warm — the warm↔gaming strobe (2026-05-31, same bug class as
# the 2026-05-12 transit face-flutter incident). 3s + the 2s poll requires ≥2
# consecutive non-flicker True frames; well under perceptible "I'm back"
# latency. Mirrors the corridor's CORRIDOR_RETURN_DESK_SECONDS streak.
RETURN_DESK_SUSTAIN_SECONDS = 3

# Re-fire cooldown after a deactivate. A presence flicker right after a
# deactivate can't immediately re-arm the override — the dwell is held off for
# this long so the worst case is ≤1 warm pulse per cooldown window instead of
# the 30–80s strobe. Invisible on a genuine long absence (the cooldown lapses
# long before the 10s dwell + activate would complete). Mirrored in
# TransitLightingService.
REFIRE_COOLDOWN_SECONDS = 45

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

# Sticky desk-confirmation window — mirrors TransitLightingService's
# DESK_STICKY_SECONDS (kept local rather than imported to avoid a
# cross-service dependency, same pattern as FACE_TRUST_THRESHOLD above).
# The desktop pc_agent posts a raw, un-debounced face_present every frame
# and PresenceFusion retains only the latest reading per source, so
# is_at_desk_fresh() flips false on a single head-down / lean-back frame.
# During desk gaming that let the absent-dwell timer accumulate and fire
# the kitchen brighten on flicker (GH#109). Treating a desk confirmation
# within this window as "still at desk" bridges the per-frame drops via the
# fusion high-water mark while a genuine exit still arms within ~25s
# (15s sticky + 10s absent dwell).
DESK_STICKY_SECONDS = 15


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
# Started at 80 (2026-05-28); bumped to 100 after user feedback the
# hallway spill wasn't quite bright enough at 1am. Still well below the
# evening kitchen target (120) so the corridor reads as path-light not
# wake-up.
CORRIDOR_L1_BRI = 100
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

# Return-to-desk debounce: face_present must be True across the streak
# threshold before we trigger wind-down. Was 3s initially, tightened to
# 1s after the 2026-05-28 bathroom-trip showed face flicker during
# settle-in repeatedly reset the streak — net 9s perceived wind-down
# latency vs Transit's instant-deactivate on the same signal.
#
# Effective wall-clock gate is ~2s, not 1s: with POLL_INTERVAL_SECONDS=2,
# the first True frame sets the streak start; the next True frame (one
# tick later, 2s) crosses the threshold and fires wind-down. A solitary
# single-frame false positive (someone walks past the monitor between
# ticks) can't fire on its own — it needs a second True frame to follow.
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
        # Leading edge of a sustained is_at_desk_fresh() streak on the
        # evening/night kitchen-only path — debounces the return-to-desk
        # deactivate against single-frame presence flicker (see
        # RETURN_DESK_SUSTAIN_SECONDS). Distinct from the corridor's own
        # _corridor_return_streak_start.
        self._return_streak_start: Optional[datetime] = None
        # When the kitchen-only path last deactivated — gates the re-fire
        # cooldown (see REFIRE_COOLDOWN_SECONDS).
        self._last_deactivated_at: Optional[datetime] = None
        # Edge authority: a DeskExit cue may arm only after this service has
        # observed a real/recent Desk confirmation. Losing all physical evidence
        # while Watching must not manufacture a synthetic "left the desk" edge.
        self._desk_departure_armed: bool = False
        # Only log block-reason transitions, not every silent tick.
        self._last_block_reason: Optional[str] = None

        # Measure-then-hold lux for D1 baseline-relative path brightness.
        # Sampled ONCE from the Latitude (living-room) camera at the moment
        # of activation — before any boost — and held until deactivate so
        # the boosted L1/kitchen don't feed back into the reading and
        # oscillate. None when the camera reading wasn't fresh at sample
        # time → path_light_brightness falls back to the fixed constants.
        self._held_lux: Optional[float] = None
        self._held_baseline: Optional[float] = None

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
            self._desk_departure_armed = False
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
            strong_zone = self._strong_presence_elsewhere(cam_status)
            if strong_zone is not None:
                await self._deactivate(f"strong presence elsewhere (zone={strong_zone})")
                return
            if self._automation.is_at_desk_fresh():
                # Require a SUSTAINED return before deactivating — a single
                # recovered face_present frame must not release the kitchen
                # (that was the warm↔gaming strobe driver). Mirrors the
                # corridor return-streak.
                if self._return_streak_start is None:
                    self._return_streak_start = now
                elif (
                    now - self._return_streak_start
                ).total_seconds() >= RETURN_DESK_SUSTAIN_SECONDS:
                    await self._deactivate("returned to desk")
                return
            # Lost the fresh-desk signal again — reset the return streak so a
            # later flicker has to re-accumulate from scratch.
            self._return_streak_start = None
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
            self._desk_departure_armed = False
            self._record_block(f"mode={mode} (not in trigger set)")
            return
        if period not in TRIGGER_PERIODS:
            self._desk_departure_armed = False
            self._record_block(f"period={period} (not in trigger set)")
            return

        # Re-fire cooldown — after a deactivate, hold off re-arming so a
        # presence flicker can't immediately re-grab the kitchen and resume
        # the strobe. Reset the absent timer too so the dwell can't pre-charge
        # during the cooldown; a fresh full ABSENT_TRIGGER_SECONDS dwell is
        # still required once the cooldown lapses.
        if self._last_deactivated_at is not None and (
            now - self._last_deactivated_at
        ).total_seconds() < REFIRE_COOLDOWN_SECONDS:
            self._camera_absent_since = None
            self._record_block("refire cooldown")
            return

        # Unknown/blinded physical authority is not evidence of an empty room.
        # Do not arm path lighting until at least one camera frame can make a
        # trustworthy present/absent decision again.
        if not self._presence_authority_ready(cam_status):
            self._camera_absent_since = None
            self._record_block("presence authority unknown")
            return

        # While Anthony is still at the desk, reset the absent timer. Use the
        # sticky gate (fresh zone=desk OR a recent fusion confirmation) so a
        # per-frame face_present flicker during desk gaming doesn't restart
        # the dwell timer and fire the kitchen brighten (GH#109).
        if self._at_desk_or_recent():
            self._desk_departure_armed = True
            self._camera_absent_since = None
            self._record_unblock()
            return

        # Strong fused presence somewhere else (Bed/Couch) means this was
        # not a kitchen trip. Desktop Bed can now suppress this path even when
        # the Latitude is absent or emitting a weak furniture-like face.
        strong_zone = self._strong_presence_elsewhere(cam_status)
        if strong_zone is not None:
            self._desk_departure_armed = False
            self._camera_absent_since = None
            self._record_block(f"strong presence elsewhere (zone={strong_zone})")
            return

        if not self._desk_departure_armed:
            self._camera_absent_since = None
            self._record_block("awaiting fresh desk before exit")
            return

        # Eligible ? a prior Desk confirmation has now been lost and no strong
        # elsewhere presence explains the transition. Start the absent dwell.
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
        # the corridor-specific dwell threshold. Unknown/blinded physical
        # authority is not evidence of an empty room.
        if not self._presence_authority_ready(cam_status):
            self._camera_absent_since = None
            self._record_block("corridor: presence authority unknown")
            return

        # Sticky gate (see _at_desk_or_recent) so desk-gaming flicker
        # doesn't arm the corridor.
        if self._at_desk_or_recent():
            self._desk_departure_armed = True
            self._camera_absent_since = None
            self._record_unblock()
            return

        # Strong fused presence elsewhere means the user settled in another
        # physical zone rather than entering the unseen hallway.
        strong_zone = self._strong_presence_elsewhere(cam_status)
        if strong_zone is not None:
            self._desk_departure_armed = False
            self._camera_absent_since = None
            self._record_block(f"corridor: strong presence elsewhere (zone={strong_zone})")
            return

        if not self._desk_departure_armed:
            self._camera_absent_since = None
            self._record_block("corridor: awaiting fresh desk before exit")
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

        strong_zone = self._strong_presence_elsewhere(cam_status)
        if strong_zone is not None:
            if self._corridor_substate != CORRIDOR_WINDDOWN_KITCHEN:
                await self._corridor_start_winddown(
                    f"strong presence elsewhere (zone={strong_zone})",
                )
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
        # Measure-then-hold for the whole corridor sequence: sample once
        # here so the L1 ramp AND the kitchen ramp (≈2s later) share one
        # pre-boost lux reading.
        self._sample_lux()
        self._desk_departure_armed = False
        l1_bri = path_light_brightness(
            self._held_lux, self._held_baseline, "late_night",
            kind="corridor_l1", fallback=CORRIDOR_L1_BRI,
        )
        states = {
            "1": {"on": True, "bri": l1_bri, "ct": CORRIDOR_L1_CT},
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
        k_bri = path_light_brightness(
            self._held_lux, self._held_baseline, "late_night",
            kind="corridor_kitchen", fallback=CORRIDOR_KITCHEN_BRI,
        )
        kitchen = {"on": True, "bri": k_bri, "ct": CORRIDOR_KITCHEN_CT}
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
        self._held_lux = None
        self._held_baseline = None

    def _record_block(self, reason: str) -> None:
        if reason != self._last_block_reason:
            logger.info("DeskExit: blocked (%s)", reason)
            self._last_block_reason = reason
            self._camera_absent_since = None

    def _record_unblock(self) -> None:
        if self._last_block_reason is not None:
            logger.info("DeskExit: unblocked (was %s)", self._last_block_reason)
            self._last_block_reason = None

    @staticmethod
    def _presence_authority_ready(cam_status: dict) -> bool:
        """Whether camera absence can be treated as real evidence."""
        explicit = cam_status.get("presence_authority_ready")
        if explicit is not None:
            return bool(explicit)
        return cam_status.get("last_detection") in {"present", "absent"}

    def _strong_presence_elsewhere(self, cam_status: dict) -> Optional[str]:
        """Return a fresh strong non-desk physical zone, if any.

        Prefer PresenceFusion so desktop Bed and Latitude Couch obey the same
        source-strength rules. The raw-camera fallback preserves boot/tests
        where fusion is not wired.
        """
        if self._presence_fusion is not None:
            zone = self._presence_fusion.latest_strong_zone()
            return zone if zone is not None and zone != "desk" else None

        detection = cam_status.get("last_detection", "unknown")
        source = cam_status.get("detection_source")
        confidence = cam_status.get("confidence", 0.0) or 0.0
        zone = cam_status.get("zone")
        if (
            detection == "present"
            and zone is not None
            and zone != "desk"
            and (
                source == "pose"
                or (source == "face" and confidence >= KITCHEN_FACE_TRUST_THRESHOLD)
            )
        ):
            return zone
        return None

    def _at_desk_or_recent(self) -> bool:
        """Flicker-robust 'is Anthony at the desk?' for the arming paths.

        ``is_at_desk_fresh()`` alone flips false on a single un-debounced
        face_present=False frame from the desktop pc_agent (PresenceFusion
        keeps only the latest reading per source), which let the absent-dwell
        timer accumulate and fire the kitchen brighten during desk gaming
        (GH#109). Fall back to the fusion high-water mark — a desk
        confirmation within DESK_STICKY_SECONDS bridges those per-frame drops
        without delaying a genuine exit beyond the sticky window.

        Used only on the ARMING side. The active-clear / return-to-desk
        paths keep their own debounce streaks (RETURN_DESK_SUSTAIN_SECONDS /
        CORRIDOR_RETURN_DESK_SECONDS) and are intentionally left on the raw
        fresh signal.
        """
        if self._automation.is_at_desk_fresh():
            return True
        if self._presence_fusion is not None:
            since = self._presence_fusion.seconds_since_at_desk()
            return since is not None and since <= DESK_STICKY_SECONDS
        return False

    def _sample_lux(self) -> None:
        """Sample the Latitude (living-room) lux once for measure-then-hold.

        Stores ``(ema_lux, baseline_lux)`` — both None when the camera
        reading isn't fresh (disabled, paused, uncalibrated, stale), in
        which case ``path_light_brightness`` returns the fixed fallback.
        """
        try:
            lux, baseline = self._automation._read_fresh_camera_lux()
        except Exception:  # defensive — never let a lux read break the cue
            lux, baseline = None, None
        self._held_lux = lux
        self._held_baseline = baseline

    def _kitchen_states(self, period: str) -> dict[str, dict]:
        if period == "evening":
            fallback_bri, ct = BRI_EVENING, KITCHEN_CT_EVENING
        else:
            fallback_bri, ct = BRI_NIGHT, KITCHEN_CT_NIGHT
        # Baseline-relative: darker living room → brighter path light, up to
        # the curated cap; held lux keeps it stable until return. Compute
        # bri ONCE and copy to both pendants (kitchen-pair rule).
        bri = path_light_brightness(
            self._held_lux, self._held_baseline, period,
            kind="desk_exit_kitchen", fallback=fallback_bri,
        )
        kitchen = {"on": True, "bri": bri, "ct": ct}
        return {"3": dict(kitchen), "4": dict(kitchen)}

    async def _activate(self, mode: str, period: str, *, repaint: bool = False) -> None:
        # Measure-then-hold: sample lux ONLY on a true activation. A repaint
        # (period rollover while held active) recomputes brightness from the
        # SAME held sample, never re-sampling — re-evaluating while boosted
        # would let L1/kitchen feed back into the camera and oscillate.
        if not repaint:
            self._sample_lux()
            self._desk_departure_armed = False
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
            self._return_streak_start = None
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
        self._return_streak_start = None
        self._held_lux = None
        self._held_baseline = None
        self._last_deactivated_at = datetime.now(tz=TZ)
        self._desk_departure_armed = False
        logger.info("DeskExit deactivated (%s)", reason)

    async def close(self) -> None:
        if self._active:
            await self._deactivate("service shutdown")
        if self._corridor_active:
            await self._corridor_full_deactivate("service shutdown")
