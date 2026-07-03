"""Tests for DeskExitKitchenService — the evening/night kitchen-only path's
release hysteresis + re-fire cooldown.

Guards the 2026-05-31 fix for the warm↔gaming strobe: the kitchen-only path
used to deactivate on the FIRST is_at_desk_fresh()==True frame (no sustain),
and since the desktop pc_agent's face_present signal is last-write-wins with
no debounce, a single recovered frame released the kitchen → the mode-apply
loop repainted the gaming palette → a real ≥10s gap re-armed and re-fired
warm. The fix adds RETURN_DESK_SUSTAIN_SECONDS (sustain before release) and
REFIRE_COOLDOWN_SECONDS (hold-off before re-arming).

The late_night corridor path has its own debounce and is not exercised here
(period is pinned to evening/night so the corridor branch is never taken).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from backend.services.desk_exit_kitchen_service import (
    ABSENT_TRIGGER_SECONDS,
    DESK_STICKY_SECONDS,
    HARD_TIMEOUT_SECONDS,
    REFIRE_COOLDOWN_SECONDS,
    RETURN_DESK_SUSTAIN_SECONDS,
    DeskExitKitchenService,
)
from backend.services.presence_fusion import PresenceFusion, PresenceReading

TZ = ZoneInfo("America/Indiana/Indianapolis")


class _FakeAutomation:
    """Engine stub exposing only what DeskExitKitchenService consumes on the
    evening/night kitchen-only path."""

    def __init__(self, mode: str = "gaming", period: str = "evening",
                 at_desk: bool = False, lux=None, baseline=None) -> None:
        self._mode = mode
        self._period = period
        self._at_desk = at_desk
        self._lux = lux
        self._baseline = baseline
        self.lux_read_calls = 0
        self.apply_calls: list[dict] = []
        self.clear_calls: list[dict] = []

    def _read_fresh_camera_lux(self):
        """Mirror the engine's (ema_lux, baseline_lux) freshness getter.

        Default (None, None) makes the service fall back to its fixed
        constants — preserving the pre-D1 behavior the older tests assert.
        """
        self.lux_read_calls += 1
        return self._lux, self._baseline

    @property
    def current_mode(self) -> str:
        return self._mode

    def _get_time_period(self) -> str:
        return self._period

    def is_at_desk_fresh(self) -> bool:
        return self._at_desk

    async def apply_desk_exit_override(self, states, duration_seconds, transition_time):
        self.apply_calls.append(
            {"states": states, "duration": duration_seconds, "transition": transition_time}
        )

    async def clear_desk_exit_override(self, transition_time=20):
        self.clear_calls.append({"transition": transition_time})


class _FakeCamera:
    def __init__(
        self,
        enabled: bool = True,
        last_detection: str = "absent",
        detection_source: Optional[str] = None,
        confidence: float = 0.0,
        zone: Optional[str] = None,
        posture: Optional[str] = None,
    ) -> None:
        self.enabled = enabled
        self.last_detection = last_detection
        self.detection_source = detection_source
        self.confidence = confidence
        self.zone = zone
        self.posture = posture

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "last_detection": self.last_detection,
            "detection_source": self.detection_source,
            "confidence": self.confidence,
            "zone": self.zone,
            "posture": self.posture,
        }


def _make_service(mode="gaming", period="evening", at_desk=False,
                  cam_detection="absent", cam_detection_source=None,
                  cam_confidence=0.0, cam_zone=None, lux=None, baseline=None):
    auto = _FakeAutomation(
        mode=mode, period=period, at_desk=at_desk, lux=lux, baseline=baseline,
    )
    cam = _FakeCamera(
        last_detection=cam_detection, detection_source=cam_detection_source,
        confidence=cam_confidence, zone=cam_zone,
    )
    return DeskExitKitchenService(auto, cam), auto, cam


async def _drive_absent_window(svc):
    """Drive the service through the ABSENT_TRIGGER_SECONDS window so it
    reaches its activate decision (mirrors the transit test helper)."""
    await svc._check()  # seeds the absent timer
    if svc._camera_absent_since is not None:
        svc._camera_absent_since -= timedelta(seconds=ABSENT_TRIGGER_SECONDS + 1)
    await svc._check()  # fires _activate


class TestActivate:
    async def test_activates_on_sustained_desk_absence(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.apply_calls) == 1
        # Kitchen pair only.
        assert set(auto.apply_calls[0]["states"].keys()) == {"3", "4"}

    async def test_blocks_when_at_desk_fresh(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening", at_desk=True)
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.apply_calls == []

    async def test_blocks_in_day_period(self):
        svc, auto, _ = _make_service(mode="gaming", period="day")
        await _drive_absent_window(svc)
        assert svc.active is False


class TestStickyDeskArming:
    """GH#109: is_at_desk_fresh() flips false on a single un-debounced
    face_present=False desktop frame (last-write-wins in PresenceFusion),
    which let the absent-dwell timer accumulate and fire the kitchen brighten
    during desk gaming. The arming path now also consults the fusion at-desk
    high-water mark (DESK_STICKY_SECONDS), so a recent desk confirmation
    suppresses the brighten through per-frame flicker.
    """

    @staticmethod
    def _fusion_at_desk(age_seconds: float):
        fusion = PresenceFusion()
        now = datetime.now(timezone.utc)
        fusion.on_observation(PresenceReading(
            source="desktop",
            captured_at=now - timedelta(seconds=age_seconds),
            face_present=True, face_confidence=0.9, zone="desk",
        ))
        # A current no-face frame on top → is_at_desk_fresh() is False, but
        # the high-water mark is unmoved.
        fusion.on_observation(PresenceReading(
            source="desktop", captured_at=now, face_present=False,
        ))
        return fusion

    async def test_recent_desk_suppresses_brighten_despite_flicker(self):
        # Engine reports NOT at desk (flicker frame), but fusion confirmed the
        # desk 2s ago → arming must stay blocked.
        auto = _FakeAutomation(mode="gaming", period="evening", at_desk=False)
        cam = _FakeCamera(last_detection="absent")
        svc = DeskExitKitchenService(
            auto, cam, presence_fusion=self._fusion_at_desk(2.0),
        )
        await _drive_absent_window(svc)
        assert svc.active is False
        assert auto.apply_calls == []

    async def test_fires_once_sticky_window_lapses(self):
        # Last desk confirmation older than the sticky window and engine says
        # not-at-desk → genuine exit, kitchen brightens.
        auto = _FakeAutomation(mode="gaming", period="evening", at_desk=False)
        cam = _FakeCamera(last_detection="absent")
        svc = DeskExitKitchenService(
            auto, cam,
            presence_fusion=self._fusion_at_desk(DESK_STICKY_SECONDS + 5),
        )
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.apply_calls) == 1


class TestReleaseHysteresis:
    """A single recovered is_at_desk_fresh() frame must NOT release the
    kitchen — only a SUSTAINED return does (RETURN_DESK_SUSTAIN_SECONDS)."""

    async def test_single_fresh_frame_does_not_deactivate(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        # First fresh-desk frame: starts the return streak, does NOT release.
        auto._at_desk = True
        await svc._check()
        assert svc.active is True
        assert svc._return_streak_start is not None
        assert auto.clear_calls == []

    async def test_deactivates_after_sustained_return(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        auto._at_desk = True
        await svc._check()  # streak starts
        assert svc.active is True
        # Backdate the streak past the sustain threshold; next fresh frame fires.
        svc._return_streak_start -= timedelta(seconds=RETURN_DESK_SUSTAIN_SECONDS + 1)
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_flicker_false_resets_the_streak(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        # True → streak starts.
        auto._at_desk = True
        await svc._check()
        assert svc._return_streak_start is not None

        # False frame (face flicker) → streak resets, still active.
        auto._at_desk = False
        await svc._check()
        assert svc._return_streak_start is None
        assert svc.active is True

        # True again → streak re-seeds from scratch (a stale long-ago start
        # can't satisfy the sustain on the next frame).
        auto._at_desk = True
        await svc._check()
        assert svc._return_streak_start is not None
        assert svc.active is True


class TestRefireCooldown:
    """After a deactivate, a presence flicker must not immediately re-arm the
    kitchen — REFIRE_COOLDOWN_SECONDS blocks it (the strobe driver)."""

    async def test_deactivate_stamps_cooldown(self):
        svc, _, _ = _make_service(mode="gaming", period="evening")
        assert svc._last_deactivated_at is None
        await _drive_absent_window(svc)
        assert svc.active is True
        await svc._deactivate("test")
        assert svc._last_deactivated_at is not None

    async def test_cooldown_blocks_immediate_refire(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True
        await svc._deactivate("test")
        assert len(auto.apply_calls) == 1

        # Re-arm attempt within the cooldown window (frozen ~0s elapsed):
        # blocked, and the dwell can't even seed.
        await _drive_absent_window(svc)
        assert svc.active is False
        assert svc._camera_absent_since is None
        assert len(auto.apply_calls) == 1

    async def test_refire_allowed_after_cooldown_lapses(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        await svc._deactivate("test")

        svc._last_deactivated_at -= timedelta(seconds=REFIRE_COOLDOWN_SECONDS + 1)
        await _drive_absent_window(svc)
        assert svc.active is True
        assert len(auto.apply_calls) == 2


class TestInstantExitsRegression:
    """Real state exits (not flicker) must still deactivate immediately —
    the hysteresis only guards the return-to-desk path."""

    async def test_mode_left_trigger_set_deactivates_instantly(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        auto._mode = "cooking"  # outside TRIGGER_MODES
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_period_left_trigger_set_deactivates_instantly(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        auto._period = "day"  # outside TRIGGER_PERIODS
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1

    async def test_hard_timeout_deactivates(self):
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert svc.active is True

        svc._activate_ts -= timedelta(seconds=HARD_TIMEOUT_SECONDS + 1)
        await svc._check()
        assert svc.active is False
        assert len(auto.clear_calls) == 1


class TestLuxAdaptiveBrightness:
    """D1: kitchen path brightness scales with the held living-room lux.

    The fixed BRI_EVENING/BRI_NIGHT become the camera-down fallback; a fresh
    Latitude lux drives a baseline-relative value, sampled once at activation
    and held (measure-then-hold) across repaints.
    """

    async def test_fresh_dark_lux_brightens_above_fallback(self):
        # Dark living room (lux 12, baseline 74) at night → near the curve's
        # hi (70), well above the fixed BRI_NIGHT fallback (60).
        svc, auto, _ = _make_service(
            mode="gaming", period="night", lux=12.0, baseline=74.0,
        )
        await _drive_absent_window(svc)
        assert svc.active
        bri = auto.apply_calls[-1]["states"]["3"]["bri"]
        assert bri > 60  # adapted up for the dark room
        assert auto.apply_calls[-1]["states"]["3"]["bri"] == \
            auto.apply_calls[-1]["states"]["4"]["bri"]  # kitchen pair matched

    async def test_bright_room_dims_below_fallback(self):
        # Room at/above baseline → lands on the lo anchor (30), below the
        # fixed BRI_NIGHT fallback — minimal path light when it's already lit.
        svc, auto, _ = _make_service(
            mode="gaming", period="night", lux=80.0, baseline=74.0,
        )
        await _drive_absent_window(svc)
        assert auto.apply_calls[-1]["states"]["3"]["bri"] == 30

    async def test_no_lux_uses_fixed_fallback(self):
        # Camera reading not fresh (None) → exact pre-D1 fixed value.
        from backend.services.desk_exit_kitchen_service import BRI_EVENING
        svc, auto, _ = _make_service(mode="gaming", period="evening")
        await _drive_absent_window(svc)
        assert auto.apply_calls[-1]["states"]["3"]["bri"] == BRI_EVENING

    async def test_measure_then_hold_repaint_does_not_resample(self):
        # Activate (1 sample), then a period repaint must reuse the held
        # sample — never re-read lux (else L1/kitchen feed back + oscillate).
        svc, auto, _ = _make_service(
            mode="gaming", period="evening", lux=12.0, baseline=74.0,
        )
        await _drive_absent_window(svc)
        assert svc.active
        assert auto.lux_read_calls == 1
        held_evening_bri = auto.apply_calls[-1]["states"]["3"]["bri"]
        # Roll the period to night while held active → repaint path.
        auto._period = "night"
        await svc._check()
        # Repaint happened (new apply with the night ct) but no new sample.
        assert auto.lux_read_calls == 1
        assert auto.apply_calls[-1]["states"]["3"]["ct"] == 375  # night ct
        # Held lux carried into the night curve (≠ the evening value).
        assert auto.apply_calls[-1]["states"]["3"]["bri"] != held_evening_bri

    async def test_deactivate_clears_held_lux(self):
        svc, auto, _ = _make_service(
            mode="gaming", period="night", lux=12.0, baseline=74.0,
        )
        await _drive_absent_window(svc)
        assert svc._held_lux == 12.0
        await svc._deactivate("test")
        assert svc._held_lux is None
        assert svc._held_baseline is None
