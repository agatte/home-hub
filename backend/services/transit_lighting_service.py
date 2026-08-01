"""Transit lighting — briefly brighten the navigation path when Anthony steps
out of the bedroom.

When the camera loses him (working / gaming / watching / relax modes where the
kitchen and living room are dim or off), briefly raise L1 / L3 / L4 to a gentle
"I can see where I'm going" level so he doesn't have to manually switch modes
or turn lights on. L2 is untouched — the bedroom bias lamp stays on the
current mode's state for when he sits back down.

State machine:
  idle ─[camera absent ≥10s + eligible mode + non-stationary zone]─> active
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

from backend.services.camera_service import FACE_TRUST_THRESHOLD
from backend.services.heartbeat import HeartbeatRegistry
from backend.services.light_state_calculator import path_light_brightness

logger = logging.getLogger("home_hub.transit_lighting")

TZ = ZoneInfo("America/Indiana/Indianapolis")

# Poll cadence — matches the camera's 2s polling so we react promptly.
POLL_INTERVAL_SECONDS = 2

# How long camera must report "absent" before we consider Anthony in transit.
# Restored from 4s → 10s (2026-05-17) after the desk-flap incident: during a
# gaming session at the desk, pose/face detection regularly drops for 4-8s
# stretches (head down typing, lean-in, brief occlusion) producing ~6s
# present↔absent cycles that crossed the 4s gate ~14×/15min and fired
# transit on each cycle. 10s sustained absence is unambiguous — the camera
# flap pattern doesn't reach it; a real bedroom-to-kitchen walk does. The
# original tighten to 4s (2026-04-26) was motivated by "walk felt slow,"
# but in practice the user experience cost of false fires was worse than
# the ~6s latency cost of being more conservative. Camera's own 15-frame
# absent threshold (~30s) still trails this so transit fires before the
# camera lane decides Anthony has gone idle.
ABSENT_TRIGGER_SECONDS = 10

# How long camera must report "present" before we revert — protects against
# a one-frame false positive flipping the lights back too eagerly.
PRESENT_CLEAR_SECONDS = 2

# Failsafe: if we never see him return, drop the override after this long.
# Matches the deadline passed to ``apply_transit_override``.
HARD_TIMEOUT_SECONDS = 600

# Re-fire cooldown after a deactivate. A presence flicker right after a
# deactivate can't immediately re-arm transit — the dwell is held off this
# long so the worst case is ≤1 transit pulse per cooldown window rather than
# a rapid re-grab. Invisible on a genuine long absence (the cooldown lapses
# well before a fresh ABSENT_TRIGGER_SECONDS dwell would complete). Mirrored
# in DeskExitKitchenService.
REFIRE_COOLDOWN_SECONDS = 45

# Modes where kitchen / living room are dim or off and transit lighting is
# worth firing. Intentionally conservative — cooking is already bright, social
# has a medium palette, sleeping wants to stay dark, gameday is handled
# elsewhere.
TRIGGER_MODES = frozenset({"working", "gaming", "watching", "relax"})

# Zones where transit lighting must NOT fire — Anthony is stationary, not
# transiting. Two painful zones:
#   • bed — face / pose detection flickers wildly under blankets in low
#     light (consecutive frames swing 0.0 → 0.99 → 0.0 confidence), and
#     absent each glitch would otherwise raise L1 + L3 + L4 every few
#     seconds.
#   • desk — added 2026-05-17. Face confidence oscillates the 0.70 trust
#     threshold during normal desk posture (lean-in, head-down typing,
#     turning to side monitor); pose detection drops on the same poses.
#     A single all-paths-miss poll seeds the 4s absent dwell, which fired
#     transit 23×/30min during a gaming session at the desk (log
#     evidence 2026-05-17). Symmetric with the bed pattern.
# Gate is on the *committed* zone reading (15s hysteresis inside
# camera_service), so brief absences don't drop the gate either. Real
# exits still fire transit via the BED_EXIT_ABSENT_FRAMES bypass below.
# "couch" added 2026-05-27 with the Latitude→living-room move: the couch is
# the living-room equivalent of bed/desk — a settled spot, not a transit cue.
STATIONARY_ZONES = frozenset({"bed", "desk", "couch"})

# Bypass STATIONARY_ZONES when camera has been continuously NOT-strongly-
# present for this many polls. Strong presence = pose detection OR face
# above TRANSIT_FACE_TRUST_THRESHOLD. The streak resets to 0 on any
# strongly-present frame — pose-flicker scenarios always include occasional
# strong frames, but a real bedroom/desk exit produces sustained absence
# (the only "presence" signal during a real exit is weak-face from
# chair-back / picture-frame false positives, which don't count toward
# the streak). 5 polls ≈ 10s at the camera's 2s cadence; transit fires
# ~10s after Anthony actually gets up. Name retains the BED_ prefix for
# git-history continuity — the constant gates both bed and desk zones.
BED_EXIT_ABSENT_FRAMES = 5

# How recently PresenceFusion must have confirmed the desk for transit to
# treat the user as stationary-at-desk. The desktop pc_agent posts a raw,
# un-debounced face_present every frame and PresenceFusion keeps only the
# latest reading per source, so `latest_zone()`/`is_at_desk_fresh()` flip to
# null on a single head-down / lean-back frame. Reading the Latitude camera
# zone (the pre-fix source) was even worse: post-2026-05-27 relocation it
# sees only the living-room couch and reports `zone=null` while Anthony is at
# the BEDROOM desk, so the STATIONARY_ZONES gate never engaged and transit
# fired on every desk-gaming flicker (~3,491 writes/7d, GH#109). This sticky
# window bridges those per-frame drops via the fusion high-water mark
# (`seconds_since_at_desk`, never reset by a non-confirming frame). 15s
# matches camera_service's committed-zone hysteresis; combined with the 10s
# absent dwell a genuine desk exit still fires transit within ~25s, while
# desk-gaming flicker (sub-15s gaps) never crosses it. Unlike the couch/bed
# committed-zone path below, the desk-sticky block does NOT honor the
# BED_EXIT_ABSENT_FRAMES bypass — the sticky-window release IS its real-exit
# detector, so a long head-down streak isn't mistaken for leaving.
DESK_STICKY_SECONDS = 15

# Face confidence below which transit treats the detection as "not really
# there." Imported from camera_service so the two stay in lockstep — values
# below this are commonly chair-backs / picture frames / wall art that
# clear MIN_FACE_CONFIDENCE but aren't actually Anthony. 2026-05-05
# verification: with him out of the bedroom for 90s+, the camera reported
# `detection_source=face, confidence~0.49` continuously (chair-back),
# which kept consecutive_absent pinned at 0 and blocked transit.
TRANSIT_FACE_TRUST_THRESHOLD = FACE_TRUST_THRESHOLD

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
        presence_fusion: Any = None,
    ) -> None:
        self._automation = automation_engine
        self._camera = camera_service
        # Optional multi-source presence layer — when wired, the
        # strong-presence calc consults it so the desktop camera can
        # defeat a Latitude chair-back FP (and vice versa).
        self._presence_fusion = presence_fusion

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
        # Polls in a row where the camera failed to report strong presence
        # (pose, or face above TRANSIT_FACE_TRUST_THRESHOLD). Used to bypass
        # the STATIONARY_ZONES gate when sustained — see BED_EXIT_ABSENT_FRAMES.
        # Resets to 0 on any strongly-present frame.
        self._strong_absent_streak: int = 0
        # Transit is edge-triggered: one activation is allowed only after a
        # fresh strong-presence observation. Continuous absence cannot create
        # repeated synthetic walks after a timeout/deactivation.
        self._presence_armed: bool = False
        # When transit last deactivated — gates the re-fire cooldown so a
        # presence flicker can't immediately re-grab the lights (see
        # REFIRE_COOLDOWN_SECONDS).
        self._last_deactivated_at: Optional[datetime] = None
        # Lights this service actually painted on the most recent _activate.
        # Used to scope _deactivate's clear to only OUR keys in the shared
        # `_transit_light_overrides` dict — `DeskExitKitchenService` also
        # writes to that dict (its `apply_desk_exit_override` is a wrapper
        # around `apply_transit_override`). Before this was tracked, transit
        # deactivating on `zone=bed` mid-DeskExit-active stomped the kitchen
        # pair back to working/late_night = OFF (incident 2026-05-18 01:56
        # ET: DeskExit fired L3+L4 bri=60 at 01:56:00, transit deactivated at
        # 01:56:10 with `light_ids=None` → clear-all → kitchen back to OFF
        # before the user reached the kitchen).
        self._owned_lights: set[str] = set()
        self._heartbeat: Optional[HeartbeatRegistry] = None

    def set_heartbeat_registry(self, registry: HeartbeatRegistry) -> None:
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
        # bedroom. sleeping / cooking / social overrides naturally fall
        # outside TRIGGER_MODES and continue to block.
        mode = getattr(self._automation, "current_mode", "idle")

        # Camera may be disabled (opt-in); bail if no camera signal available.
        cam_status = self._camera.get_status() if self._camera else {}
        if not cam_status.get("enabled"):
            # Reset any trigger timer so we don't fire the moment the camera
            # comes back online.
            self._camera_absent_since = None
            self._presence_during_absent_since = None
            self._strong_absent_streak = 0
            self._presence_armed = False
            if self._active:
                await self._deactivate("camera disabled")
            self._record_block("camera disabled")
            return

        detection = cam_status.get("last_detection", "unknown")
        src = cam_status.get("detection_source")
        conf = cam_status.get("confidence", 0.0) or 0.0

        # Stationary-zone signal. The Latitude camera zone alone is wrong
        # post-relocation — it sees the couch, so it reports null while
        # Anthony is at the bedroom desk (the desktop owns that zone via
        # PresenceFusion). Prefer the fused zone, fall back to the raw
        # Latitude reading for boot/test paths where fusion isn't wired.
        fused_zone = None
        if self._presence_fusion is not None:
            fused_zone = self._presence_fusion.latest_zone()
        zone = fused_zone or cam_status.get("zone")
        # Desk is flicker-prone (raw per-frame face_present, last-write-wins
        # in fusion), so latest_zone() drops to null on a single head-down
        # frame. The sticky high-water mark survives those drops — treat a
        # desk confirmation within DESK_STICKY_SECONDS as stationary-at-desk.
        desk_sticky = False
        if self._presence_fusion is not None:
            since = self._presence_fusion.seconds_since_at_desk()
            desk_sticky = since is not None and since <= DESK_STICKY_SECONDS

        # Strong presence = pose detection OR face above the trust threshold.
        # Weak-face-only counts as absent for transit's purposes — chair-back /
        # picture-frame false positives clear MIN_FACE_CONFIDENCE indefinitely
        # while Anthony is actually away, so we can't trust them.
        strongly_present = detection == "present" and (
            src == "pose"
            or (src == "face" and conf >= TRANSIT_FACE_TRUST_THRESHOLD)
        )
        # Multi-source: a desktop face-present reading is high-confidence
        # at-desk, so reset the absent streak even if the Latitude camera
        # is flapping or wedged. Keeps the chair-back-FP defeat working
        # when the desktop sees Anthony head-on.
        if not strongly_present and self._presence_fusion is not None:
            strongly_present = self._presence_fusion.is_strongly_present_any()
        if strongly_present:
            self._strong_absent_streak = 0
        else:
            self._strong_absent_streak += 1

        # ── If already active: look for conditions to clear ──
        if self._active:
            # Effective mode out of the trigger set (sleeping, cooking, social,
            # idle) → revert. Manual overrides to a trigger mode are fine.
            if mode not in TRIGGER_MODES:
                await self._deactivate(f"mode exited trigger set (mode={mode})")
                return

            # Camera now sees him in a stationary zone (couch/bed) or the
            # desk is freshly confirmed again — he didn't walk to the kitchen,
            # he sat back down. Revert immediately so the transit lift doesn't
            # linger after he's clearly settled.
            if desk_sticky or zone in STATIONARY_ZONES:
                where = "desk" if desk_sticky else zone
                if strongly_present:
                    self._presence_armed = True
                await self._deactivate(f"zone={where} (user stationary)")
                return

            # Hard timeout — belt-and-suspenders against stuck state
            if self._transit_start and (now - self._transit_start).total_seconds() >= HARD_TIMEOUT_SECONDS:
                await self._deactivate("hard timeout")
                return

            # Camera sees him again — revert after brief dwell. Use strong
            # presence so weak-face false positives don't prematurely revert.
            if strongly_present:
                if self._camera_present_since is None:
                    self._camera_present_since = now
                elif (now - self._camera_present_since).total_seconds() >= PRESENT_CLEAR_SECONDS:
                    self._presence_armed = True
                    await self._deactivate("camera returned")
                    return
            else:
                self._camera_present_since = None
            return

        # ── Not active: look for conditions to activate ──
        # A strong observation establishes the presence session even when the
        # user is stationary at the desk/couch. It must happen before the
        # stationary-zone gates below; those gates prevent activation, but
        # should not prevent the later present→absent edge from being known.
        if strongly_present and not self._presence_armed:
            self._presence_armed = True
            self._camera_absent_since = None
            self._presence_during_absent_since = None

        if mode not in TRIGGER_MODES:
            self._record_block(f"mode={mode} (not in trigger set)")
            return

        # Re-fire cooldown — after a deactivate, hold off re-arming so a
        # presence flicker can't immediately re-grab the lights and resume a
        # strobe. _record_block clears the absent/flap timers, so a fresh full
        # ABSENT_TRIGGER_SECONDS dwell is still required once the cooldown
        # lapses.
        if self._last_deactivated_at is not None and (
            now - self._last_deactivated_at
        ).total_seconds() < REFIRE_COOLDOWN_SECONDS:
            self._record_block("refire cooldown")
            return

        # Watching + reclined: user is consuming content, not navigating —
        # even if zone is null/uncommitted. Closes the 2026-05-12 incident
        # where the camera's zone decommitted mid-watching-session and
        # transit fired 107× / 30min on face-detection flutter
        # (confidence ~0.30 bouncing across the trust threshold). The
        # STATIONARY_ZONES gate below only fires when zone is committed
        # as "bed"; this gate catches the same intent via posture when
        # the zone signal isn't reliable.
        posture = cam_status.get("posture")
        if mode == "watching" and posture == "reclined":
            self._record_block("watching+reclined (user not navigating)")
            return

        # Desk freshly confirmed (within the sticky window) → he's at the
        # desk, not navigating. Block unconditionally — the sticky-window
        # release (seconds_since_at_desk > DESK_STICKY_SECONDS) is itself the
        # real-exit detector, so the BED_EXIT_ABSENT_FRAMES bypass must NOT
        # apply: a long head-down / lean-back streak climbs the absent streak
        # but is not an exit. This is the gate that was silently dead pre-fix
        # (Latitude zone=null at the bedroom desk → never matched, GH#109).
        if desk_sticky:
            self._record_block("zone=desk (sticky — user at desk)")
            return

        # Last committed zone is couch/bed → he's settled in the living room
        # or bedroom. Camera absences in this state are usually detection
        # flicker (face/pose tossing in low light), not navigation. Block
        # before the absent-dwell timer accumulates so a flap-storm can't fire
        # transit. Exception: if we've had BED_EXIT_ABSENT_FRAMES consecutive
        # polls without strong presence, that's a real exit (flicker always
        # includes some strong frames; chair-back false positives don't count
        # toward the streak). Couch/bed use the Latitude committed zone, which
        # already carries 15s hysteresis in camera_service.
        if zone in STATIONARY_ZONES:
            if self._strong_absent_streak < BED_EXIT_ABSENT_FRAMES:
                self._record_block(f"zone={zone} (user stationary)")
                return

        # All gates clear — log the unblock so journalctl shows when the
        # service became eligible again.
        self._record_unblock()

        if not self._presence_armed:
            self._record_block("awaiting fresh presence before exit")
            return

        if strongly_present:
            if self._camera_absent_since is None:
                # Not currently waiting on the absent dwell — nothing to debounce.
                self._presence_during_absent_since = None
                return
            # Already mid-dwell: a single strong-present frame might be a
            # transient pose detection. Require PRESENT_CLEAR_SECONDS of
            # sustained strong presence before treating it as a true return.
            if self._presence_during_absent_since is None:
                self._presence_during_absent_since = now
                return
            if (now - self._presence_during_absent_since).total_seconds() >= PRESENT_CLEAR_SECONDS:
                logger.info(
                    "Transit: absent timer reset (sustained strong-present for %ss)",
                    PRESENT_CLEAR_SECONDS,
                )
                self._camera_absent_since = None
                self._presence_during_absent_since = None
            # Else: still inside flap window — keep the absent timer running.
            return

        # Not strongly present — clear flap tracking and advance the dwell.
        self._presence_during_absent_since = None
        if self._camera_absent_since is None:
            self._camera_absent_since = now
            logger.info(
                "Transit: absent timer started (mode=%s)", mode,
            )
            return

        if (now - self._camera_absent_since).total_seconds() >= ABSENT_TRIGGER_SECONDS:
            self._presence_armed = False
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

    def _navigation_states(self, mode: str) -> dict[str, dict]:
        """Per-light targets for transit. Lower at late-night to avoid glare.

        Yields the kitchen pair to ``DeskExitKitchenService`` when it owns
        the path: productive modes (working / gaming / watching / idle) in
        evening / night periods get a brighter, hold-until-return kitchen
        from the dedicated service, so transit only paints L1 in that
        window. Outside the yield window (eg relax-evening, working-day),
        transit still paints all three lights.
        """
        hour = datetime.now(tz=TZ).hour
        late_night = hour >= LATE_NIGHT_START_HOUR or hour < LATE_NIGHT_END_HOUR

        # Baseline-relative path brightness (D1): scale L1 + kitchen by how
        # dark the living room actually is, via the Latitude camera. Sampled
        # once here (transit fires this only at activate, so it's inherently
        # measure-then-hold for the 10-min window). Transit's two tiers map
        # onto the curve's "night" (late_night) / "evening" (otherwise) rows;
        # the legacy fixed values stay as the camera-down fallback. CT is
        # unchanged.
        try:
            lux, baseline = self._automation._read_fresh_camera_lux()
        except Exception:
            lux, baseline = None, None
        curve_period = "night" if late_night else "evening"
        ct = 400 if late_night else 360
        l1_fallback = 60 if late_night else 120
        kitchen_fallback = 40 if late_night else 80
        l1_bri = path_light_brightness(
            lux, baseline, curve_period, kind="transit_l1", fallback=l1_fallback,
        )
        kitchen_bri = path_light_brightness(
            lux, baseline, curve_period, kind="transit_kitchen",
            fallback=kitchen_fallback,
        )
        living_room = {"on": True, "bri": l1_bri, "ct": ct}
        kitchen = {"on": True, "bri": kitchen_bri, "ct": ct}

        # L1 = living room, L3 = kitchen front, L4 = kitchen back. L2 (bedroom
        # bias) is left on the current mode's state so walking back into the
        # bedroom feels continuous.
        states: dict[str, dict] = {"1": living_room}
        # Cede kitchen during the productive evening/night window so the two
        # services don't fight: transit would set kitchen to 40 bri while
        # DeskExitKitchenService wants 60–120 for the same desk-exit event.
        # Hour-based check matches DeskExitKitchen's TRIGGER_PERIODS (evening
        # 18:00+, night = winddown_start_hour onward, late_night above) — we
        # use a simple hour gate here to avoid importing the schedule.
        productive_yield = mode in {"working", "gaming", "watching", "idle"}
        evening_or_night = hour >= 18 or late_night
        if not (productive_yield and evening_or_night):
            states["3"] = kitchen
            states["4"] = kitchen
        # At late_night specifically, also cede L1 to DeskExitKitchen's
        # corridor: the corridor fires at the 5s desk-absent threshold and
        # ramps L1 to bri=80, but transit fires at 10s with bri=60 and
        # overwrote the corridor's L1 four seconds later (2026-05-28
        # bathroom-trip incident: L1 brighten then dim mid-ramp). At
        # evening/night transit still owns L1 — corridor is late_night-only.
        if productive_yield and late_night:
            states.pop("1", None)
        return states

    async def _activate(self, mode: str) -> None:
        states = self._navigation_states(mode)
        if not states:
            # All lights ceded (productive evening/night with only kitchen in
            # the prior version's payload) — nothing to do here, DeskExit
            # owns the cue. Don't stamp active state.
            logger.info(
                "Transit yielded (mode=%s) — DeskExitKitchen owns the path",
                mode,
            )
            return
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
        self._owned_lights = set(states.keys())
        logger.info(
            "Transit lighting activated (mode=%s, lights=%s)",
            mode, list(states.keys()),
        )

    async def _deactivate(self, reason: str) -> None:
        if not self._active:
            return
        # Scope the clear to only the lights we actually painted. The shared
        # `_transit_light_overrides` dict also holds DeskExitKitchen's
        # stamps; clearing with light_ids=None would stomp those too.
        owned = list(self._owned_lights) if self._owned_lights else None
        await self._automation.clear_transit_override(
            light_ids=owned, transition_time=30,
        )
        self._active = False
        self._camera_absent_since = None
        self._camera_present_since = None
        self._presence_during_absent_since = None
        self._transit_start = None
        self._owned_lights = set()
        self._last_deactivated_at = datetime.now(tz=TZ)
        logger.info("Transit lighting deactivated (%s)", reason)

    async def close(self) -> None:
        """Shutdown hook — release any active override so lights revert cleanly."""
        if self._active:
            await self._deactivate("service shutdown")
