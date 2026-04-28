"""Tests for TransitLightingService — activate / deactivate state machine
under the override-aware mode check.

The regression these tests guard against: winddown sets a manual relax
override at 22:00, which used to block transit lighting from firing for
the rest of the night because the activate path returned early on any
manual_override. Fix uses the effective (override-aware) mode and only
blocks when that mode falls outside TRIGGER_MODES.
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

    async def clear_transit_override(self, transition_time=30):
        self.clear_calls.append({"transition": transition_time})


class _FakeCamera:
    def __init__(
        self,
        enabled: bool = True,
        last_detection: str = "absent",
        zone: Optional[str] = None,
    ) -> None:
        self.enabled = enabled
        self.last_detection = last_detection
        self.zone = zone

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "last_detection": self.last_detection,
            "zone": self.zone,
        }


def _make_service(mode="working", override=False, override_mode=None,
                  cam_detection="absent", cam_enabled=True,
                  cam_zone=None):
    auto = _FakeAutomation(mode=mode, manual_override=override, override_mode=override_mode)
    cam = _FakeCamera(enabled=cam_enabled, last_detection=cam_detection, zone=cam_zone)
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

    async def test_activates_when_camera_absent_and_eligible_mode(self):
        svc, auto, _ = _make_service(mode="working")
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1
        # Per-light targets cover L1 + L3 + L4 (kitchen + living-room).
        assert set(auto.transit_calls[0]["states"].keys()) == {"1", "3", "4"}

    async def test_activates_when_override_mode_is_relax(self):
        # The regression scenario: winddown set relax override; user walks to
        # kitchen. Pre-fix this never fired. Post-fix it does.
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

    async def test_activates_when_zone_is_desk(self):
        # Walked away from the desk; zone is still "desk" (last commit).
        # This is the canonical transit-firing case and must still work.
        svc, auto, cam = _make_service(
            mode="working", cam_zone="desk",
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.transit_calls) == 1

    async def test_activates_when_zone_is_unknown(self):
        # Stub cameras (older tests) and pre-commit windows return None for
        # zone — fall through to the existing absent-dwell logic.
        svc, auto, cam = _make_service(mode="working", cam_zone=None)
        await _drive_absent_window(svc)
        assert svc.active is True

    async def test_deactivates_when_zone_flips_to_bed_mid_transit(self):
        # Transit fired while he was at his desk; he then sat down on the
        # bed (zone commits to "bed"). Service should revert immediately —
        # not wait for camera to report "present" or for the hard timeout.
        svc, auto, cam = _make_service(mode="working", cam_zone="desk")
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.clear_calls) == 0

        cam.zone = "bed"
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
        # Locked-in invariant: only "bed" is stationary today.
        # If/when "couch" or another stationary zone gets committed
        # by the camera, it should be added here too.
        assert "bed" in STATIONARY_ZONES
        assert "desk" not in STATIONARY_ZONES


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
        states = svc._navigation_states()
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
        states = svc._navigation_states()
        assert states["1"]["bri"] == 120
        assert states["3"]["bri"] == 80
        assert states["4"]["bri"] == 80


class _FrozenDatetime:
    """Minimal datetime stand-in so _navigation_states sees a fixed hour."""

    def __init__(self, year, month, day, hour, minute):
        self._args = (year, month, day, hour, minute)

    def now(self, tz=None):
        return datetime(*self._args, tzinfo=tz or TZ)
