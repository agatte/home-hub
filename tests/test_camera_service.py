"""
Tests for the camera presence detection service.

All tests mock cv2.VideoCapture and mediapipe.solutions.face_detection
so no real camera is needed. Tests verify presence/absence logic,
absent countdown, graceful degradation, and automation engine priority.
"""

import asyncio
from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.camera_service import (
    ABSENT_THRESHOLD,
    POLL_INTERVAL,
    CameraService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    ws_manager=None, automation=None, ml_logger=None
) -> CameraService:
    """Create a CameraService with mocked dependencies."""
    ws = ws_manager or AsyncMock()
    auto = automation or AsyncMock()
    ml = ml_logger or AsyncMock()
    return CameraService(ws_manager=ws, automation_engine=auto, ml_logger=ml)


def _mock_detection(score: float, origin_x: int = 100, width: int = 50):
    """Create a mock MediaPipe Tasks API detection result.

    ``origin_x`` + ``width`` populate the ``bounding_box`` used by the
    zone-mapping code in ``_process_frame``. Defaults sit center-ish in
    a 320×240 frame so the computed zone is deterministic in tests.
    """
    category = MagicMock()
    category.score = score
    det = MagicMock()
    det.categories = [category]
    det.bounding_box.origin_x = origin_x
    det.bounding_box.width = width
    return det


@pytest.fixture(autouse=True)
def _stub_cv2_and_mediapipe():
    """Inject fake cv2 + mediapipe modules so camera_service's lazy imports succeed in CI."""
    mock_cv2 = MagicMock()
    # Pass frames through unchanged — preserves numpy array mean() for ambient_lux tests
    mock_cv2.resize.side_effect = lambda frame, size: frame
    mock_cv2.cvtColor.side_effect = lambda frame, code: frame

    mock_mp = MagicMock()

    with patch.dict("sys.modules", {"cv2": mock_cv2, "mediapipe": mock_mp}):
        yield


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    """Verify service initialization behavior."""

    def test_disabled_by_default(self):
        service = _make_service()
        assert service.enabled is False
        assert service._cap is None

    def test_status_when_disabled(self):
        service = _make_service()
        status = service.get_status()
        assert status["enabled"] is False
        assert status["last_detection"] == "unknown"


# ---------------------------------------------------------------------------
# Presence detection logic
# ---------------------------------------------------------------------------


class TestPresenceLogic:
    """Test the _process_frame → presence/absent determination."""

    def test_process_frame_present(self):
        """Face detected → returns present with confidence."""
        service = _make_service()
        service._enabled = True

        # Mock VideoCapture
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        import numpy as np
        fake_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, fake_frame)
        service._cap = mock_cap

        # Mock face detector (Tasks API uses .detect() not .process())
        mock_detector = MagicMock()
        mock_results = MagicMock()
        mock_results.detections = [_mock_detection(0.92)]
        mock_detector.detect.return_value = mock_results
        service._face_detector = mock_detector

        result = service._process_frame()
        assert result is not None
        assert result["status"] == "present"
        assert result["confidence"] == pytest.approx(0.92)
        assert "ambient_lux" in result

    def test_process_frame_absent(self):
        """No face detected → returns absent."""
        service = _make_service()
        service._enabled = True

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        import numpy as np
        fake_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, fake_frame)
        service._cap = mock_cap

        mock_detector = MagicMock()
        mock_results = MagicMock()
        mock_results.detections = []
        mock_detector.detect.return_value = mock_results
        service._face_detector = mock_detector

        result = service._process_frame()
        assert result is not None
        assert result["status"] == "absent"
        assert result["confidence"] == 0.0

    def test_process_frame_camera_read_failure(self):
        """Camera read fails → returns None."""
        service = _make_service()
        service._enabled = True

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)
        service._cap = mock_cap

        result = service._process_frame()
        assert result is None


# ---------------------------------------------------------------------------
# Absent countdown
# ---------------------------------------------------------------------------


class TestAbsentCountdown:
    """Verify the 3-frame absent countdown triggers idle mode."""

    @pytest.mark.asyncio
    async def test_absent_triggers_after_threshold(self):
        """ABSENT_THRESHOLD consecutive absent frames → reports idle."""
        automation = AsyncMock()
        service = _make_service(automation=automation)
        service._enabled = True

        for _ in range(ABSENT_THRESHOLD):
            service._consecutive_absent += 1

        # Simulate the threshold being reached
        assert service._consecutive_absent == ABSENT_THRESHOLD

    @pytest.mark.asyncio
    async def test_present_resets_absent_counter(self):
        """Present frame after absent frames → resets counter."""
        service = _make_service()
        service._enabled = True
        service._consecutive_absent = 2  # 2 absent frames

        # Simulate present detection
        service._consecutive_absent = 0
        assert service._consecutive_absent == 0

    @pytest.mark.asyncio
    async def test_present_after_absent_reports_idle(self):
        """Present detection after being absent → reports idle to automation."""
        automation = AsyncMock()
        service = _make_service(automation=automation)
        service._enabled = True
        service._was_absent = True
        service._consecutive_absent = 0

        # Simulate what poll_loop does when present after a long absence
        service._was_absent = False
        await automation.report_activity(mode="idle", source="camera")

        automation.report_activity.assert_called_once_with(
            mode="idle", source="camera"
        )

    def test_clear_committed_zone_posture(self):
        """Clearing helper drops both zone and posture commits (and candidates)."""
        from datetime import datetime, timezone

        service = _make_service()
        service._last_zone = "bed"
        service._last_zone_at = datetime.now(timezone.utc)
        service._candidate_zone = "desk"
        service._candidate_zone_since = datetime.now(timezone.utc)
        service._last_posture = "reclined"
        service._last_posture_at = datetime.now(timezone.utc)
        service._candidate_posture = "upright"
        service._candidate_posture_since = datetime.now(timezone.utc)

        service._clear_committed_zone_posture("test")

        assert service._last_zone is None
        assert service._last_zone_at is None
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None
        assert service._last_posture is None
        assert service._last_posture_at is None
        assert service._candidate_posture is None
        assert service._candidate_posture_since is None


class TestFreshnessRefreshOnConfirm:
    """Steady-state confirmation refreshes the commit timestamp.

    Without this, ``zone_committed_at`` / ``posture_committed_at`` only
    update on TRANSITIONS, so a user who has been in the same zone for
    >5 min (ZONE_POSTURE_FRESHNESS_SECONDS) appears stale to the lighting
    overlay's freshness gate and Branch 3 (bed-zone dim) silently
    disengages even while the camera is actively observing the user.
    """

    def test_zone_steady_state_refreshes_timestamp(self):
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        # Simulate an initial commit ~10 min ago.
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_zone_at = old

        # Camera frame still confirms zone=bed.
        service._apply_zone_hysteresis("bed")

        # Timestamp must have moved forward.
        assert service._last_zone_at is not None
        assert service._last_zone_at > old
        # And must be very recent.
        delta = (datetime.now(timezone.utc) - service._last_zone_at).total_seconds()
        assert delta < 1.0

    def test_zone_brief_absence_preserves_timestamp(self):
        """candidate=None during a brief absence must NOT refresh
        (we only refresh on active confirmation)."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_zone_at = old

        service._apply_zone_hysteresis(None)

        # Timestamp unchanged — absence preserves but doesn't refresh.
        assert service._last_zone_at == old

    def test_posture_steady_state_refreshes_timestamp(self):
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_posture = "reclined"
        service._last_posture_at = old

        service._apply_posture_hysteresis("reclined")

        assert service._last_posture_at is not None
        assert service._last_posture_at > old
        delta = (
            datetime.now(timezone.utc) - service._last_posture_at
        ).total_seconds()
        assert delta < 1.0

    def test_posture_none_does_not_refresh(self):
        """For posture, candidate=None means 'not observed this poll'
        (face-only path) — preserve but don't refresh."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_posture = "reclined"
        service._last_posture_at = old

        service._apply_posture_hysteresis(None)

        assert service._last_posture_at == old

    def test_zone_weak_face_present_refreshes_timestamp(self):
        """Weak-face frames emit zone=None to suppress chair-back zone-flips,
        but the user is still observed-present — the prior commit is
        semantically current and must refresh so the lighting overlay's
        300s freshness gate keeps honoring it.

        Repro of the bug observed 2026-05-08: bed+reclined committed at
        04:38, dim-room weak-face dominated for the next 8 minutes,
        commit went stale, overlay disengaged, L2 sat at working
        baseline (189 bri) instead of the bed-reclined dim (5 bri).
        """
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_zone_at = old

        # Weak-face frame: zone=None but person observed.
        service._apply_zone_hysteresis(None, present_observed=True)

        assert service._last_zone_at is not None
        assert service._last_zone_at > old
        delta = (datetime.now(timezone.utc) - service._last_zone_at).total_seconds()
        assert delta < 1.0
        # Committed value must be untouched — the whole point of weak-face
        # zone=None is "trust the prior commit, don't re-disambiguate."
        assert service._last_zone == "bed"

    def test_posture_face_only_present_refreshes_timestamp(self):
        """Strong-face-without-pose and weak-face frames both emit
        posture=None. Posture freshness must refresh while the user is
        present so the bed+reclined overlay branch keeps firing in dim
        rooms where pose detection is intermittent."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_posture = "reclined"
        service._last_posture_at = old

        service._apply_posture_hysteresis(None, present_observed=True)

        assert service._last_posture_at is not None
        assert service._last_posture_at > old
        delta = (
            datetime.now(timezone.utc) - service._last_posture_at
        ).total_seconds()
        assert delta < 1.0
        assert service._last_posture == "reclined"

    def test_zone_present_no_prior_commit_does_not_refresh(self):
        """If we've never committed a zone, present_observed=True with
        candidate=None has nothing to refresh against — leave _last_zone_at
        as None. (Edge case: camera just turned on, weak-face on first frame.)"""
        service = _make_service()
        assert service._last_zone is None
        assert service._last_zone_at is None

        service._apply_zone_hysteresis(None, present_observed=True)

        assert service._last_zone_at is None

    def test_posture_present_no_prior_commit_does_not_refresh(self):
        """Mirror of the zone case for posture."""
        service = _make_service()
        assert service._last_posture is None
        assert service._last_posture_at is None

        service._apply_posture_hysteresis(None, present_observed=True)

        assert service._last_posture_at is None

    def test_zone_change_still_commits_with_fresh_timestamp(self):
        """Regression guard: the steady-state refresh must not break
        the existing transition-commit path."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_zone_at = old

        # Fire enough hysteresis ticks to commit a change to "desk".
        # Set candidate state directly to simulate >ZONE_HYSTERESIS_SECONDS held.
        from backend.services.camera_service import ZONE_HYSTERESIS_SECONDS
        service._candidate_zone = "desk"
        service._candidate_zone_since = (
            datetime.now(timezone.utc)
            - timedelta(seconds=ZONE_HYSTERESIS_SECONDS + 1)
        )

        service._apply_zone_hysteresis("desk")

        assert service._last_zone == "desk"
        assert service._last_zone_at > old
        assert service._candidate_zone is None

    def test_sustained_observation_keeps_freshness_gate_open(self):
        """End-to-end regression for the 2026-05-01 Branch 3 silently
        disengaging bug: simulate 6 minutes of continuous frames all
        observing zone=bed, then confirm the AutomationEngine's
        ``_fresh_camera_attr`` (production caller) still returns "bed".

        Pre-fix: zone_committed_at would be set once on the initial
        commit and never refreshed; after 5 minutes, freshness gate
        returned None and Branch 3 disengaged silently.

        Post-fix: every confirming frame refreshes _last_zone_at, so
        the freshness gate stays satisfied indefinitely as long as the
        camera keeps observing the user.
        """
        from datetime import datetime, timedelta, timezone

        from backend.services.automation_engine import AutomationEngine
        from backend.services.light_state_calculator import (
            ZONE_POSTURE_FRESHNESS_SECONDS,
        )

        service = _make_service()
        engine = AutomationEngine(
            hue=MagicMock(),
            hue_v2=MagicMock(),
            ws_manager=AsyncMock(),
        )

        # Initial commit was 10 min ago — well past the 300s freshness window.
        # Mirrors the real-world condition: Anthony went to bed at some earlier
        # point, hasn't transitioned zones since.
        very_old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_zone_at = very_old

        # If we read the freshness gate RIGHT NOW (before any confirming frame),
        # it would return None — that's the broken pre-fix behavior.
        assert engine._fresh_camera_attr(
            service, "zone", "zone_committed_at"
        ) is None, "pre-confirmation should look stale"

        # Simulate 180 frames of camera saying "bed" (one frame every 2s = 6 min
        # of poll loop activity). Even one confirming frame should be enough,
        # but we run 180 to verify steady-state behavior under sustained load.
        for _ in range(180):
            service._apply_zone_hysteresis("bed")

        # After confirmation, _last_zone_at must be fresh enough that the
        # AutomationEngine's freshness gate returns the zone, NOT None.
        zone = engine._fresh_camera_attr(service, "zone", "zone_committed_at")
        assert zone == "bed", (
            f"freshness gate should return 'bed' after sustained observation; "
            f"got {zone!r}. _last_zone_at age: "
            f"{(datetime.now(timezone.utc) - service._last_zone_at).total_seconds():.1f}s"
        )

        # Posture path mirrors zone — same regression coverage.
        old_posture = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_posture = "reclined"
        service._last_posture_at = old_posture
        assert engine._fresh_camera_attr(
            service, "posture", "posture_committed_at"
        ) is None
        for _ in range(180):
            service._apply_posture_hysteresis("reclined")
        posture = engine._fresh_camera_attr(
            service, "posture", "posture_committed_at"
        )
        assert posture == "reclined"

        # Belt-and-suspenders: explicit age check matches the freshness window.
        zone_age = (
            datetime.now(timezone.utc) - service._last_zone_at
        ).total_seconds()
        assert zone_age < ZONE_POSTURE_FRESHNESS_SECONDS


# ---------------------------------------------------------------------------
# Ambient lux
# ---------------------------------------------------------------------------


class TestAmbientLux:
    """Verify ambient light calculation from frame luminance."""

    def test_lux_from_dark_frame(self):
        """Black frame → lux near 0."""
        import numpy as np

        service = _make_service()
        service._enabled = True

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        dark_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, dark_frame)
        service._cap = mock_cap

        mock_detector = MagicMock()
        mock_results = MagicMock()
        mock_results.detections = []
        mock_detector.detect.return_value = mock_results
        service._face_detector = mock_detector

        result = service._process_frame()
        assert result["ambient_lux"] == pytest.approx(0.0)

    def test_lux_from_bright_frame(self):
        """White frame → lux near 255."""
        import numpy as np

        service = _make_service()
        service._enabled = True

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        bright_frame = np.full((240, 320, 3), 255, dtype=np.uint8)
        mock_cap.read.return_value = (True, bright_frame)
        service._cap = mock_cap

        mock_detector = MagicMock()
        mock_results = MagicMock()
        mock_results.detections = []
        mock_detector.detect.return_value = mock_results
        service._face_detector = mock_detector

        result = service._process_frame()
        assert result["ambient_lux"] == pytest.approx(255.0)


# ---------------------------------------------------------------------------
# Mode change callback
# ---------------------------------------------------------------------------


class TestModeChangeCallback:
    """Verify camera pauses during sleeping mode."""

    @pytest.mark.asyncio
    async def test_pauses_on_sleeping(self):
        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()
        service._cap.isOpened.return_value = True

        await service.on_mode_change("sleeping")
        assert service._paused is True
        service._cap.release.assert_called_once()

    @pytest.mark.asyncio
    async def test_resumes_on_non_sleeping(self):
        service = _make_service()
        service._enabled = True
        service._paused = True

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = mock_cap

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            await service.on_mode_change("idle")

        assert service._paused is False

    @pytest.mark.asyncio
    async def test_resume_clears_committed_zone_posture(self):
        """Stale bed/reclined from the night before must not survive sleep.

        Regression: the overlay reads ``camera.zone`` / ``camera.posture``
        directly. Without clearing on resume, the morning's first ticks
        consume bed/reclined values that were last committed before bed —
        dimming the room for "watching reclined" all morning.
        """
        from datetime import datetime, timezone

        service = _make_service()
        service._enabled = True
        service._paused = True
        service._last_zone = "bed"
        service._last_zone_at = datetime.now(timezone.utc)
        service._last_posture = "reclined"
        service._last_posture_at = datetime.now(timezone.utc)

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = mock_cap

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            await service.on_mode_change("idle")

        assert service._last_zone is None
        assert service._last_zone_at is None
        assert service._last_posture is None
        assert service._last_posture_at is None


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify service handles missing camera/dependencies gracefully."""

    def test_process_frame_no_cap(self):
        """No VideoCapture → returns None without error."""
        service = _make_service()
        service._cap = None
        assert service._process_frame() is None

    @pytest.mark.asyncio
    async def test_close_when_not_started(self):
        """Closing a never-started service doesn't crash."""
        service = _make_service()
        await service.close()
        assert service.enabled is False


# ---------------------------------------------------------------------------
# Automation engine priority
# ---------------------------------------------------------------------------


class TestCameraSourcePriority:
    """Verify camera source priority rules in automation engine."""

    @pytest.mark.asyncio
    async def test_camera_idle_does_not_override_gaming(self):
        """Camera 'idle' should not override process-detected 'gaming'."""
        from backend.services.automation_engine import MODE_PRIORITY

        # Camera reports idle, but process says gaming.
        # Same priority check still applies: idle (1) < gaming (5).
        assert MODE_PRIORITY["gaming"] > MODE_PRIORITY["idle"]

    @pytest.mark.asyncio
    async def test_camera_idle_does_not_downgrade_watching(self):
        """Camera 'idle' (present) should not downgrade 'watching'."""
        from backend.services.automation_engine import MODE_PRIORITY

        assert MODE_PRIORITY["watching"] > MODE_PRIORITY["idle"]


# ---------------------------------------------------------------------------
# Capture watchdog (frame-read hang recovery)
# ---------------------------------------------------------------------------


class TestCaptureWatchdog:
    """Cover the asyncio.wait_for watchdog around _process_frame.

    Regression coverage for the 2026-04-30 V4L2 hang where ``cap.read()``
    parked the executor thread for ~13.7h after a sleeping-mode reopen
    and silenced the heartbeat / lux multiplier.
    """

    def test_open_capture_sets_timeouts_and_warmup(self):
        """_open_capture sets V4L2 timeouts + resolution, then discards a warm-up frame."""
        import cv2

        service = _make_service()

        cap = service._open_capture()

        assert cap is not None
        # The autouse fixture's MagicMock returns truthy from isOpened().
        cap.isOpened.assert_called_once()
        # Property setters should fire for both timeouts AND resolution.
        set_calls = {call.args for call in cap.set.call_args_list}
        assert (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000) in set_calls
        assert (cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000) in set_calls
        assert (cv2.CAP_PROP_FRAME_WIDTH, 640) in set_calls
        assert (cv2.CAP_PROP_FRAME_HEIGHT, 480) in set_calls
        # Exactly one warm-up read so the next _process_frame doesn't see junk.
        cap.read.assert_called_once()

    def test_open_capture_returns_none_when_device_unavailable(self):
        """Failure to open the device → returns None, doesn't raise."""
        import cv2

        service = _make_service()
        # The autouse fixture's MagicMock returns a fresh MagicMock from
        # cv2.VideoCapture(0) on each call. Force this one to look closed.
        bad_cap = MagicMock()
        bad_cap.isOpened.return_value = False
        cv2.VideoCapture.return_value = bad_cap

        try:
            assert service._open_capture() is None
        finally:
            cv2.VideoCapture.reset_mock(return_value=True, side_effect=True)

    def test_recover_capture_releases_old_and_reopens(self):
        """_recover_capture releases the wedged handle and installs a fresh one."""
        service = _make_service()
        old_cap = MagicMock()
        service._cap = old_cap

        service._recover_capture()

        old_cap.release.assert_called_once()
        assert service._cap is not None
        assert service._cap is not old_cap

    def test_recover_capture_swallows_release_exception(self):
        """A broken release() must not propagate — orphan thread may hold a soft lock."""
        service = _make_service()
        old_cap = MagicMock()
        old_cap.release.side_effect = RuntimeError("driver wedged")
        service._cap = old_cap

        # Must not raise.
        service._recover_capture()
        # Reopen still happened.
        assert service._cap is not None
        assert service._cap is not old_cap

    @pytest.mark.asyncio
    async def test_poll_loop_recovers_from_frame_timeout(self, monkeypatch):
        """A hung _process_frame trips the watchdog, triggers recovery, loop continues."""
        from backend.services import camera_service as cam_module

        # Shrink the timeout so the test doesn't sleep 5s.
        monkeypatch.setattr(cam_module, "FRAME_READ_TIMEOUT_S", 0.05)
        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0)

        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()  # truthy; _process_frame won't actually run

        # _process_frame blocks until cancelled. Run in the executor so it
        # exercises the same wait_for path the real code uses.
        import threading
        block = threading.Event()

        def hang() -> None:
            block.wait(timeout=2.0)  # bounded so a failed test still terminates

        monkeypatch.setattr(service, "_process_frame", hang)

        recover_called = False

        def fake_recover() -> None:
            nonlocal recover_called
            recover_called = True
            block.set()  # release the orphan so the executor thread can finish

        monkeypatch.setattr(service, "_recover_capture", fake_recover)

        # Drive a single iteration of poll_loop, then cancel.
        task = asyncio.create_task(service.poll_loop())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert recover_called, "Watchdog should have invoked _recover_capture"
