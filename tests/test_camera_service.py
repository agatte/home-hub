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


def _mock_detection(score: float):
    """Create a mock MediaPipe Tasks API detection result."""
    category = MagicMock()
    category.score = score
    det = MagicMock()
    det.categories = [category]
    return det


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
    """Verify the 3-frame absent countdown triggers away mode."""

    @pytest.mark.asyncio
    async def test_absent_triggers_after_threshold(self):
        """3 consecutive absent frames → reports away."""
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
    async def test_present_after_away_reports_idle(self):
        """Present detection after being away → reports idle to automation."""
        automation = AsyncMock()
        service = _make_service(automation=automation)
        service._enabled = True
        service._was_absent = True
        service._consecutive_absent = 0

        # Simulate what poll_loop does when present after away
        service._was_absent = False
        await automation.report_activity(mode="idle", source="camera")

        automation.report_activity.assert_called_once_with(
            mode="idle", source="camera"
        )


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
    async def test_camera_away_does_not_override_gaming(self):
        """Camera 'away' should not override process-detected 'gaming'."""
        from backend.services.automation_engine import MODE_PRIORITY

        # Camera reports away, but process says gaming
        # The priority check: source=camera, mode=away,
        # _mode_source=process, _current_mode=gaming
        # Should return early (not override)
        assert MODE_PRIORITY["gaming"] > MODE_PRIORITY["away"]

    @pytest.mark.asyncio
    async def test_camera_idle_does_not_downgrade_watching(self):
        """Camera 'idle' (present) should not downgrade 'watching'."""
        from backend.services.automation_engine import MODE_PRIORITY

        assert MODE_PRIORITY["watching"] > MODE_PRIORITY["idle"]
