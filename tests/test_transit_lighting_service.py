"""Tests for TransitLightingService — activate / deactivate state machine
under the override-aware mode check.

The regression these tests guard against: a manual relax override (e.g.
selected from the dashboard) used to block transit lighting from firing
because the activate path returned early on any manual_override. Fix uses
the effective (override-aware) mode and only blocks when that mode falls
outside TRIGGER_MODES.
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pytest

from backend.services.transit_lighting_service import (
    ABSENT_TRIGGER_SECONDS,
    HARD_TIMEOUT_SECONDS,
    PRESENT_CLEAR_SECONDS,
    STATIONARY_ZONES,
    TRIGGER_MODES,
    TransitLightingService,
)

TZ = ZoneInfo("America/Indiana/Indianapolis")


@pytest.fixture(autouse=True)
def _force_daytime(monkeypatch):
    """Pin the service's wall-clock reads to 10:00 local so transit's
    time-of-day gates evaluate deterministically regardless of when the
    suite runs.

    Without this, ``_navigation_states`` reads the real ``datetime.now()``:
    in productive modes during the late-night window (23:00-06:00 local) it
    cedes L1 *and* the kitchen pair to DeskExitKitchenService, yielding an
    empty payload, so ``_activate`` early-returns and ``svc.active`` never
    flips True. That made ~13 ``assert svc.active is True`` tests pass by day
    and fail late-night / on UTC CI (GH#88). 10:00 is mid-day — the
    non-ceding window — so every light transit owns is painted.

    Mirrors the ``_force_daytime`` autouse fixture in test_confidence_fusion.
    Tests needing a specific hour (TestNavigationStates) re-pin via their own
    in-body ``monkeypatch.setattr``, which overrides this default for that test.
    """
    monkeypatch.setattr(
        "backend.services.transit_lighting_service.datetime",
        _FrozenDatetime(2026, 4, 26, 10, 0),
    )


class _FakeAutomation:
    """Engine stub exposing only what TransitLightingService consumes."""

    def __init__(self, mode: str = "working", manual_override: bool = False,
                 override_mode: Optional[str] = None) -> None:
        self._detected = mode
        self._manual_override = manual_override
        self._override_mode = override_mode
        self.transit_calls: list[dict] = []
        self.clear_calls: list[dict] = []

    @property
    def current_mode(self) -> str:
        return self._override_mode if self._manual_override else self._detected

    @property
    def manual_override(self) -> bool:
        return self._manual_override

    async def apply_transit_override(self, states, duration_seconds, transition_time):
        self.transit_calls.append(
            {"states": states, "duration": duration_seconds, "transition": transition_time}
        )

    async def clear_transit_override(self, light_ids=None, transition_time=30):
        # Production widened this signature on 2026-05-18 (537b647) so
        # transit can scope its clear to its own owned lights instead of
        # stomping DeskExitKitchenService overrides in the shared
        # _transit_light_overrides dict.
        self.clear_calls.append(
            {"light_ids": light_ids, "transition": transition_time}
        )


class _FakeCamera:
    def __init__(
        self,
        enabled: bool = True,
        last_detection: str = "absent",
        zone: Optional[str] = None,
        posture: Optional[str] = None,
        detection_source: Optional[str] = "pose",
        confidence: float = 0.95,
    ) -> None:
        self.enabled = enabled
        self.last_detection = last_detection
        self.zone = zone
        self.posture = posture
        # Defaults represent "strong presence" so tests that set
        # last_detection="present" without specifying source/confidence
        # match the pre-2026-05-05 semantics where any present counted.
        self.detection_source = detection_source
        self.confidence = confidence

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "last_detection": self.last_detection,
            "zone": self.zone,
            "posture": self.posture,
            "detection_source": self.detection_source,
            "confidence": self.confidence,
        }


def _make_service(mode="working", override=False, override_mode=None,
                  cam_detection="absent", cam_enabled=True,
                  cam_zone=None, cam_posture=None,
                  cam_detection_source="pose", cam_confidence=0.95):
    auto = _FakeAutomation(mode=mode, manual_override=override, override_mode=override_mode)
    cam = _FakeCamera(
        enabled=cam_enabled, last_detection=cam_detection, zone=cam_zone,
        posture=cam_posture, detection_source=cam_detection_source,
        confidence=cam_confidence,
    )
    return TransitLightingService(auto, cam), auto, cam


async def _drive_absent_window(svc):
    """Drive the service through the ABSENT_TRIGGER_SECONDS window so the
    state machine reaches its activate decision."""
    # First tick seeds the absent timer.
    await svc._check()
    # Backdate the timer past the trigger window so the next tick fires.
    if svc._camera_absent_since is not None:
        from datetime import timedelta
        svc._camera_absent_since -= timedelta(seconds=ABSENT_TRIGGER_SECONDS + 1)
    await svc._check()


class TestActivateGuards:
    """The activate path: when (and only when) should transit fire?"""

    async def test_activates_when_camera_absent_and_eligible_mode(
        self, monkeypatch,
    ):
        # Pin to mid-day so the productive-evening kitchen-cede (working in
        # evening/late_night → L3/L4 yielded to DeskExitKitchen, shipped
        # 88725d8 on 2026-05-18) doesn't reduce the payload to L1-only.
        # The non-ceding window is the legitimate "transit owns all three"
        # path this test asserts. Productive-evening cede has its own test
        # in TestNavigationStates.
        monkeypatch.setattr(
            "backend.services.transit_lighting_service.datetime",
            _FrozenDatetime(2026, 4, 26, 10, 0),
        )
        svc, auto, _ = _make_service(mode="working")
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1
        # Per-light targets cover L1 + L3 + L4 (kitchen + living-room).
        assert set(auto.transit_calls[0]["states"].keys()) == {"1", "3", "4"}

    async def test_activates_when_override_mode_is_relax(self):
        # The regression scenario: a manual relax override is active and the
        # user walks to the kitchen. Pre-fix this never fired. Post-fix it does.
        svc, auto, _ = _make_service(
            mode="working", override=True, override_mode="relax",
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_activates_when_override_mode_is_working(self):
        # Manual override to working mid-day; walks to kitchen. Should fire.
        svc, auto, _ = _make_service(
            mode="idle", override=True, override_mode="working",
        )
        await _drive_absent_window(svc)
        assert svc.active is True

    async def test_blocks_when_override_mode_is_sleeping(self):
        # User explicitly chose dark. Don't fight it.
        svc, auto, _ = _make_service(
            mode="working", override=True, override_mode="sleeping",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_blocks_when_override_mode_is_cooking(self):
        # Cooking already lights kitchen brightly — transit not needed.
        svc, auto, _ = _make_service(
            mode="working", override=True, override_mode="cooking",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_blocks_when_detected_mode_is_idle(self):
        # No override; auto-detected mode outside trigger set.
        svc, auto, _ = _make_service(mode="idle")
        await _drive_absent_window(svc)
        assert svc.active is False

class TestStationaryZoneGate:
    """Camera-committed zone=bed must not let transit fire — Anthony is
    reclined under blankets, where face / pose detection flickers wildly
    at 2 Hz. Each flicker would otherwise raise L1+L3+L4 every few seconds.
    """

    async def test_blocks_when_zone_is_bed(self):
        # In bed, manual relax override (the actual user-facing scenario).
        svc, auto, cam = _make_service(
            mode="working", override=True, override_mode="relax",
            cam_zone="bed",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_blocks_when_zone_is_desk(self):
        # 2026-05-17: desk added to STATIONARY_ZONES. Face confidence
        # oscillates the 0.70 trust threshold during normal desk posture
        # (lean-in, head-down typing), and a single all-paths-miss poll
        # would otherwise seed the 4s absent dwell. Block at the zone
        # gate instead — real desk exits go through the BED_EXIT_ABSENT_
        # FRAMES bypass (see test below).
        svc, auto, cam = _make_service(
            mode="working", cam_zone="desk",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_desk_exit_bypass_activates_after_sustained_absence(self):
        # Real desk exit (sustained, not a momentary face-conf dip) still
        # fires transit. Mirrors the bed-exit weak-face bypass: after
        # BED_EXIT_ABSENT_FRAMES polls without strong presence, the
        # STATIONARY_ZONES gate steps aside.
        from datetime import timedelta
        from backend.services.transit_lighting_service import (
            BED_EXIT_ABSENT_FRAMES,
        )
        svc, auto, cam = _make_service(
            mode="working", cam_zone="desk",
            cam_detection="absent", cam_detection_source=None,
            cam_confidence=0.0,
        )
        # Build the absent streak — gate still blocks during this window.
        for _ in range(BED_EXIT_ABSENT_FRAMES):
            await svc._check()
            assert svc.active is False
        assert svc._strong_absent_streak >= BED_EXIT_ABSENT_FRAMES

        # Next poll: gate bypasses, absent-dwell timer starts.
        await svc._check()
        assert svc._camera_absent_since is not None
        assert svc.active is False

        # Backdate dwell past trigger; tick fires.
        svc._camera_absent_since -= timedelta(seconds=ABSENT_TRIGGER_SECONDS + 1)
        await svc._check()
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_activates_when_zone_is_unknown(self):
        # Stub cameras (older tests) and pre-commit windows return None for
        # zone — fall through to the existing absent-dwell logic.
        svc, auto, cam = _make_service(mode="working", cam_zone=None)
        await _drive_absent_window(svc)
        assert svc.active is True

    async def test_deactivates_when_zone_flips_to_bed_mid_transit(self):
        # Transit fired while zone was uncommitted (mid-walk); he then sat
        # down on the bed (zone commits to "bed"). Service should revert
        # immediately — not wait for camera to report "present" or for the
        # hard timeout.
        svc, auto, cam = _make_service(mode="working", cam_zone=None)
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.clear_calls) == 0

        cam.zone = "bed"
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_deactivates_when_zone_flips_to_desk_mid_transit(self):
        # 2026-05-17: desk now in STATIONARY_ZONES. Mid-walk transit fire
        # followed by sitting back at the desk should revert immediately,
        # symmetric with the bed case above.
        svc, auto, cam = _make_service(mode="working", cam_zone=None)
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.clear_calls) == 0

        cam.zone = "desk"
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_zone_block_clears_pending_absent_timer(self):
        # Build up an absent timer with no committed zone, then zone
        # commits to "bed" — block should clear the pending timer so it
        # doesn't fire the moment zone moves back to desk.
        svc, _, cam = _make_service(mode="working", cam_zone=None)
        await svc._check()
        assert svc._camera_absent_since is not None

        cam.zone = "bed"
        await svc._check()
        assert svc._camera_absent_since is None

    def test_stationary_zones_membership(self):
        # Locked-in invariant: bed + desk are both stationary. Desk added
        # 2026-05-17 to stop the face-confidence-flutter spam fire-pattern
        # (see test_blocks_when_zone_is_desk).
        assert "bed" in STATIONARY_ZONES
        assert "desk" in STATIONARY_ZONES

    async def test_weak_face_only_bypasses_stationary_after_5_polls(self):
        # 2026-05-05 regression: when Anthony leaves the bedroom, the camera
        # often keeps reporting "present" via face detection of a chair-back
        # / picture-frame at confidence ~0.5. consecutive_absent stays at 0
        # so the simple gate-bypass never triggers. Transit's local
        # _strong_absent_streak counts these weak-face frames as not-strongly-
        # present and ticks up — after BED_EXIT_ABSENT_FRAMES polls the
        # STATIONARY_ZONES gate bypasses, the absent-dwell timer accumulates
        # for ABSENT_TRIGGER_SECONDS, then transit fires.
        from datetime import timedelta
        from backend.services.transit_lighting_service import (
            BED_EXIT_ABSENT_FRAMES,
        )
        svc, auto, cam = _make_service(
            mode="working", cam_zone="bed",
            cam_detection="present", cam_detection_source="face",
            cam_confidence=0.49,  # below TRANSIT_FACE_TRUST_THRESHOLD = 0.70
        )
        # Drive BED_EXIT_ABSENT_FRAMES polls of weak-face → still gated, but
        # the streak builds.
        for _ in range(BED_EXIT_ABSENT_FRAMES):
            await svc._check()
            assert svc.active is False
        assert svc._strong_absent_streak >= BED_EXIT_ABSENT_FRAMES

        # Next poll: gate bypasses, absent-dwell timer starts.
        await svc._check()
        assert svc._camera_absent_since is not None
        assert svc.active is False  # ABSENT_TRIGGER_SECONDS not yet met

        # Backdate the dwell so the trigger threshold is met, then tick.
        svc._camera_absent_since -= timedelta(seconds=ABSENT_TRIGGER_SECONDS + 1)
        await svc._check()
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_pose_present_resets_strong_absent_streak(self):
        # Anti-flap: while in bed, occasional pose-present frames must reset
        # the streak so transit doesn't fire from intermittent pose
        # blanket-flicker.
        from backend.services.transit_lighting_service import (
            BED_EXIT_ABSENT_FRAMES,
        )
        svc, _, cam = _make_service(
            mode="working", cam_zone="bed",
            cam_detection="present", cam_detection_source="face",
            cam_confidence=0.49,
        )
        # Tick 4 weak-face polls — streak at 4.
        for _ in range(4):
            await svc._check()
        assert svc._strong_absent_streak == 4

        # One pose frame slips in.
        cam.detection_source = "pose"
        cam.confidence = 0.92
        await svc._check()
        assert svc._strong_absent_streak == 0  # reset

        # Back to weak face — streak starts over at 1.
        cam.detection_source = "face"
        cam.confidence = 0.49
        await svc._check()
        assert svc._strong_absent_streak == 1
        assert svc.active is False


class TestWatchingReclinedGate:
    """Posture-based gate that catches the 2026-05-12 incident pattern:
    user reclined while watching content, camera's zone signal lapsed to
    null, and STATIONARY_ZONES couldn't fire its gate. Result was 107
    transit fires in 30 min on face-confidence flutter. Posture is a more
    durable signal than zone when the user is sitting still, so this
    gate covers the case where zone is uncommitted but posture says
    "definitely not navigating."
    """

    async def test_blocks_watching_reclined_with_null_zone(self):
        # The exact incident shape: mode=watching, posture=reclined,
        # zone=null (zone commit lapsed). Pre-fix would fire transit.
        # Post-fix blocks at the posture gate.
        svc, auto, _ = _make_service(
            mode="watching", cam_zone=None, cam_posture="reclined",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_blocks_watching_reclined_with_bed_zone(self):
        # Belt-and-suspenders: watching+reclined+bed should also block
        # (STATIONARY_ZONES already handles bed; this confirms no
        # interaction breaks it).
        svc, auto, _ = _make_service(
            mode="watching", cam_zone="bed", cam_posture="reclined",
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.transit_calls == []

    async def test_watching_upright_can_still_fire(self):
        # Watching mode + upright posture (sat up, walking around mid-show)
        # → user IS navigating. Transit should fire normally.
        svc, auto, _ = _make_service(
            mode="watching", cam_zone=None, cam_posture="upright",
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_working_reclined_can_still_fire(self):
        # Not watching → the watching+reclined gate doesn't engage. If
        # the user is reclined in working mode (rare — maybe a couch
        # laptop session) and the camera loses them, transit should
        # behave as before.
        svc, auto, _ = _make_service(
            mode="working", cam_zone=None, cam_posture="reclined",
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_watching_no_posture_signal_can_still_fire(self):
        # Camera reports posture=None (signal lost). Don't block on a
        # missing signal — fall through to the existing gates. This
        # tests the gate is conditional on posture EQUALING "reclined",
        # not just on watching mode.
        svc, auto, _ = _make_service(
            mode="watching", cam_zone=None, cam_posture=None,
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1


class TestFlapSuppression:
    """Pose fallback can extrapolate landmarks for partial-body frames as
    Anthony exits the camera view, producing a single-frame "present"
    detection that should NOT reset the absent dwell timer.
    """

    async def test_single_frame_present_does_not_reset_absent_timer(self):
        from datetime import timedelta
        svc, auto, cam = _make_service(
            mode="working", cam_detection="absent",
        )
        # Tick 1: absent → timer starts.
        await svc._check()
        assert svc._camera_absent_since is not None
        timer_started_at = svc._camera_absent_since

        # Tick 2: pose hallucinates "present" for one frame.
        cam.last_detection = "present"
        await svc._check()
        # Timer must survive the flap.
        assert svc._camera_absent_since == timer_started_at
        assert svc._presence_during_absent_since is not None

        # Tick 3: absent again — flap tracker clears, timer continues.
        cam.last_detection = "absent"
        await svc._check()
        assert svc._camera_absent_since == timer_started_at
        assert svc._presence_during_absent_since is None

        # Backdate the timer past ABSENT_TRIGGER_SECONDS and tick again — fires.
        svc._camera_absent_since -= timedelta(seconds=ABSENT_TRIGGER_SECONDS + 1)
        await svc._check()
        assert svc.active is True

    async def test_sustained_present_does_reset_absent_timer(self):
        from datetime import timedelta
        svc, auto, cam = _make_service(
            mode="working", cam_detection="absent",
        )
        # Tick 1: absent → timer starts.
        await svc._check()
        assert svc._camera_absent_since is not None

        # Tick 2: present (1st frame).
        cam.last_detection = "present"
        await svc._check()
        assert svc._camera_absent_since is not None  # still waiting
        assert svc._presence_during_absent_since is not None

        # Backdate the presence start past PRESENT_CLEAR_SECONDS — confirmed return.
        svc._presence_during_absent_since -= timedelta(seconds=PRESENT_CLEAR_SECONDS + 1)
        await svc._check()
        # Timer should now be fully reset.
        assert svc._camera_absent_since is None
        assert svc._presence_during_absent_since is None

    async def test_presence_tracker_clears_on_each_absent_frame(self):
        svc, _, cam = _make_service(mode="working", cam_detection="absent")
        await svc._check()  # timer starts

        # Flap to present, then back. The tracker should reset cleanly.
        cam.last_detection = "present"
        await svc._check()
        assert svc._presence_during_absent_since is not None

        cam.last_detection = "absent"
        await svc._check()
        assert svc._presence_during_absent_since is None  # cleared


class TestDeactivateGuards:
    """The deactivate path: once active, what tears it down?"""

    async def test_deactivates_when_override_flips_to_sleeping(self):
        svc, auto, cam = _make_service(mode="working")
        await _drive_absent_window(svc)
        assert svc.active is True

        # User manually flips to sleeping while transit is active.
        auto._manual_override = True
        auto._override_mode = "sleeping"
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_deactivates_when_camera_returns_for_2s(self):
        from datetime import timedelta
        svc, auto, cam = _make_service(mode="working")
        await _drive_absent_window(svc)
        assert svc.active is True

        # Camera reports present — first tick starts the dwell timer.
        cam.last_detection = "present"
        await svc._check()
        assert svc.active is True  # dwell window not satisfied yet
        # Backdate so the dwell threshold is met.
        svc._camera_present_since -= timedelta(seconds=PRESENT_CLEAR_SECONDS + 1)
        await svc._check()
        assert svc.active is False

    async def test_deactivates_on_hard_timeout(self):
        from datetime import timedelta
        svc, auto, _ = _make_service(mode="working")
        await _drive_absent_window(svc)
        assert svc.active is True

        # Backdate the start so the failsafe trips.
        svc._transit_start -= timedelta(seconds=HARD_TIMEOUT_SECONDS + 1)
        await svc._check()
        assert svc.active is False


class TestBlockReasonLogging:
    """Activate-path block reasons should log on transitions only and
    clear any pending absent dwell so a stale timer doesn't fire after
    the block lifts."""

    async def test_mode_block_clears_absent_timer(self):
        # Build up the absent timer in working mode...
        svc, auto, cam = _make_service(mode="working")
        await svc._check()
        assert svc._camera_absent_since is not None

        # ...then user manually overrides to cooking (non-trigger). Timer must clear.
        auto._manual_override = True
        auto._override_mode = "cooking"
        await svc._check()
        assert svc._camera_absent_since is None
        assert svc._last_block_reason is not None

    async def test_block_logged_only_on_reason_change(self, caplog):
        svc, auto, _ = _make_service(mode="cooking")  # blocked from the start
        with caplog.at_level("INFO", logger="home_hub.transit_lighting"):
            await svc._check()
            await svc._check()
            await svc._check()
        # Three ticks at the same block reason → exactly one log line.
        block_logs = [r for r in caplog.records if "blocked" in r.message]
        assert len(block_logs) == 1
        assert "mode=cooking" in block_logs[0].message

    async def test_unblock_logged_when_gate_clears(self, caplog):
        svc, auto, cam = _make_service(mode="cooking", cam_detection="present")
        with caplog.at_level("INFO", logger="home_hub.transit_lighting"):
            await svc._check()  # logs blocked
            auto._detected = "working"
            auto._manual_override = False
            await svc._check()  # logs unblocked
        unblock_logs = [r for r in caplog.records if "unblocked" in r.message]
        assert len(unblock_logs) == 1
        assert "was mode=cooking" in unblock_logs[0].message


class TestNavigationStates:
    """Per-light targets — late-night uses dimmer values."""

    def test_late_night_uses_dimmer_brightness(self, monkeypatch):
        svc, _, _ = _make_service()
        # 23:30 → late night
        monkeypatch.setattr(
            "backend.services.transit_lighting_service.datetime",
            _FrozenDatetime(2026, 4, 26, 23, 30),
        )
        # `relax` skips the productive-evening yield so the kitchen pair
        # stays in transit's payload. Mode arg added 2026-05-18 (88725d8)
        # when DeskExitKitchenService owned the kitchen during productive
        # evening/night windows.
        states = svc._navigation_states("relax")
        assert states["1"]["bri"] == 60
        assert states["3"]["bri"] == 40
        assert states["4"]["bri"] == 40

    def test_daytime_uses_brighter_navigation(self, monkeypatch):
        svc, _, _ = _make_service()
        # 19:00 → before late-night cutoff
        monkeypatch.setattr(
            "backend.services.transit_lighting_service.datetime",
            _FrozenDatetime(2026, 4, 26, 19, 0),
        )
        # `relax` outside the productive yield (working/gaming/watching/
        # idle + evening/late_night) keeps kitchen in the payload.
        states = svc._navigation_states("relax")
        assert states["1"]["bri"] == 120
        assert states["3"]["bri"] == 80
        assert states["4"]["bri"] == 80

    def test_productive_evening_yields_kitchen_to_desk_exit(self, monkeypatch):
        """In productive modes during evening/night, transit cedes the
        kitchen pair to DeskExitKitchenService so the two don't fight."""
        svc, _, _ = _make_service()
        monkeypatch.setattr(
            "backend.services.transit_lighting_service.datetime",
            _FrozenDatetime(2026, 4, 26, 21, 0),  # evening
        )
        states = svc._navigation_states("working")
        # L1 still painted; L3 + L4 yielded to DeskExitKitchen.
        assert "1" in states
        assert "3" not in states
        assert "4" not in states


class _FrozenDatetime:
    """Minimal datetime stand-in so _navigation_states sees a fixed hour."""

    def __init__(self, year, month, day, hour, minute):
        self._args = (year, month, day, hour, minute)

    def now(self, tz=None):
        return datetime(*self._args, tzinfo=tz or TZ)
