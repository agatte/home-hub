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

    def test_healthy_requires_active_capture_and_post_start_observation(self):
        from datetime import datetime, timezone

        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()
        assert service.healthy is False

        service._last_detection_at = datetime.now(timezone.utc)
        assert service.healthy is True

        service._paused = True
        assert service.healthy is False


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

    @pytest.mark.asyncio
    async def test_poll_loop_sustained_absence_reaches_threshold(self, monkeypatch):
        """Explicit absent frames alone drive the ABSENT_THRESHOLD teardown."""
        from datetime import datetime, timezone

        from backend.services import camera_service as cam_module
        from backend.services.camera_service import ZONE_COUCH

        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0.005)
        automation = AsyncMock()
        automation._confidence_fusion = None
        automation._presence_fusion = None
        service = _make_service(automation=automation)
        service._enabled = True
        service._cap = MagicMock()
        service._last_zone = ZONE_COUCH
        service._last_zone_at = datetime.now(timezone.utc)
        service._last_posture = "reclined"
        service._last_posture_at = datetime.now(timezone.utc)
        absent_result = {
            "status": "absent",
            "confidence": 0.0,
            "source": None,
            "pose_landmark_count": 0,
            "ambient_lux": 10.0,
            "zone": None,
            "posture": None,
        }
        monkeypatch.setattr(service, "_process_frame", lambda: absent_result)

        task = asyncio.create_task(service.poll_loop())
        try:
            for _ in range(100):
                if automation.report_activity.await_count:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("explicit absence did not reach ABSENT_THRESHOLD")
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert service._consecutive_absent >= ABSENT_THRESHOLD
        assert service._last_zone is None
        assert service._last_posture is None
        automation.report_activity.assert_awaited()

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


class TestZoneCandidateContinuity:
    """Pending zones survive only uncertain observations of a present user."""

    def test_strong_couch_candidate_starts_pending_candidacy(self):
        from backend.services.camera_service import ZONE_COUCH

        service = _make_service()

        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)

        assert service._last_zone is None
        assert service._candidate_zone == ZONE_COUCH
        assert service._candidate_zone_since is not None

    @pytest.mark.asyncio
    async def test_no_result_gap_breaks_couch_dwell_without_absence_side_effects(
        self, monkeypatch,
    ):
        """No frame result resets only the pending zone dwell."""
        from datetime import datetime, timedelta, timezone

        from backend.services import camera_service as cam_module
        from backend.services.camera_service import (
            ZONE_COUCH,
            ZONE_DESK,
            ZONE_HYSTERESIS_SECONDS,
        )

        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0.01)
        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()
        committed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        service._last_zone = ZONE_DESK
        service._last_zone_at = committed_at
        service._candidate_zone = ZONE_COUCH
        service._candidate_zone_since = datetime.now(timezone.utc) - timedelta(
            seconds=ZONE_HYSTERESIS_SECONDS + 1,
        )
        service._consecutive_absent = 4
        monkeypatch.setattr(service, "_process_frame", lambda: None)

        task = asyncio.create_task(service.poll_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert service._candidate_zone is None
        assert service._candidate_zone_since is None
        assert service._last_zone == ZONE_DESK
        assert service._last_zone_at == committed_at
        assert service._consecutive_absent == 4

        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)

        assert service._last_zone == ZONE_DESK
        assert service._candidate_zone == ZONE_COUCH
        assert service._candidate_zone_since is not None

    @pytest.mark.asyncio
    async def test_frame_processing_failure_breaks_pending_zone_continuity(
        self, monkeypatch,
    ):
        from datetime import datetime, timedelta, timezone

        from backend.services import camera_service as cam_module
        from backend.services.camera_service import ZONE_COUCH, ZONE_HYSTERESIS_SECONDS

        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0.01)
        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()
        service._candidate_zone = ZONE_COUCH
        service._candidate_zone_since = datetime.now(timezone.utc) - timedelta(
            seconds=ZONE_HYSTERESIS_SECONDS + 1,
        )
        service._consecutive_absent = 3

        def fail_processing():
            raise RuntimeError("inference failed")

        monkeypatch.setattr(service, "_process_frame", fail_processing)
        task = asyncio.create_task(service.poll_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert service._candidate_zone is None
        assert service._candidate_zone_since is None
        assert service._consecutive_absent == 3

    @pytest.mark.asyncio
    async def test_failed_capture_reopen_cannot_preserve_aged_candidate(
        self, monkeypatch,
    ):
        from datetime import datetime, timedelta, timezone

        from backend.services import camera_service as cam_module
        from backend.services.camera_service import ZONE_COUCH, ZONE_HYSTERESIS_SECONDS

        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0.01)
        service = _make_service()
        service._enabled = True
        service._candidate_zone = ZONE_COUCH
        service._candidate_zone_since = datetime.now(timezone.utc) - timedelta(
            seconds=ZONE_HYSTERESIS_SECONDS + 1,
        )

        async def unavailable_capture():
            return None

        monkeypatch.setattr(service, "_open_capture_async", unavailable_capture)
        task = asyncio.create_task(service.poll_loop())
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert service._candidate_zone is None
        assert service._candidate_zone_since is None

    def test_weak_present_preserves_existing_pending_couch(self):
        from backend.services.camera_service import ZONE_COUCH

        service = _make_service()
        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)
        started_at = service._candidate_zone_since

        service._apply_zone_hysteresis(None, present_observed=True)
        service._apply_zone_hysteresis(None, present_observed=True)

        assert service._candidate_zone == ZONE_COUCH
        assert service._candidate_zone_since == started_at
        assert service._last_zone is None

    def test_weak_present_without_prior_candidate_does_not_create_one(self):
        service = _make_service()

        service._apply_zone_hysteresis(None, present_observed=True)

        assert service._candidate_zone is None
        assert service._candidate_zone_since is None
        assert service._last_zone is None

    def test_positive_continuity_allows_later_trustworthy_couch_commit(self):
        from datetime import datetime, timedelta, timezone

        from backend.services.camera_service import (
            ZONE_COUCH,
            ZONE_HYSTERESIS_SECONDS,
        )

        service = _make_service()
        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)
        service._candidate_zone_since = (
            datetime.now(timezone.utc)
            - timedelta(seconds=ZONE_HYSTERESIS_SECONDS + 1)
        )

        service._apply_zone_hysteresis(None, present_observed=True)
        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)

        assert service._last_zone == ZONE_COUCH
        assert service._last_zone_at is not None
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None

    def test_absent_observation_cancels_pending_couch(self):
        from backend.services.camera_service import ZONE_COUCH

        service = _make_service()
        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)

        service._apply_zone_hysteresis(None, present_observed=False)

        assert service._last_zone is None
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None

    def test_conflicting_non_none_candidate_restarts_hysteresis(self):
        from datetime import datetime, timedelta, timezone

        from backend.services.camera_service import (
            ZONE_COUCH,
            ZONE_DESK,
            ZONE_HYSTERESIS_SECONDS,
        )

        service = _make_service()
        service._apply_zone_hysteresis(ZONE_COUCH, present_observed=True)
        service._candidate_zone_since = (
            datetime.now(timezone.utc)
            - timedelta(seconds=ZONE_HYSTERESIS_SECONDS + 1)
        )

        service._apply_zone_hysteresis(ZONE_DESK, present_observed=True)

        assert service._candidate_zone == ZONE_DESK
        assert service._candidate_zone_since is not None
        assert service._last_zone is None

        service._apply_zone_hysteresis(ZONE_DESK, present_observed=True)

        assert service._last_zone is None
        assert service._candidate_zone == ZONE_DESK

    def test_weak_furniture_like_face_cannot_commit_couch(self):
        import numpy as np

        from backend.services.camera_service import (
            FACE_ANCHOR_MIN_CONFIDENCE,
            LOW_LUX_FACE_FLOOR_CONF,
        )

        service = _make_service()
        service._enabled = True
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (
            True,
            np.zeros((240, 320, 3), dtype=np.uint8),
        )
        service._cap = mock_cap
        weak_confidence = LOW_LUX_FACE_FLOOR_CONF + 0.05
        assert weak_confidence < FACE_ANCHOR_MIN_CONFIDENCE
        mock_face_detector = MagicMock()
        mock_face_results = MagicMock()
        mock_face_results.detections = [_mock_detection(weak_confidence)]
        mock_face_detector.detect.return_value = mock_face_results
        service._face_detector = mock_face_detector
        service._pose_landmarker = None

        result = service._process_frame()

        assert result["status"] == "present"
        assert result["zone"] is None
        service._apply_zone_hysteresis(
            result["zone"], present_observed=result["status"] == "present",
        )
        assert service._last_zone is None
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None

    def test_committed_couch_stays_fresh_through_weak_present_frame(self):
        from datetime import datetime, timedelta, timezone

        from backend.services.camera_service import ZONE_COUCH

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = ZONE_COUCH
        service._last_zone_at = old

        service._apply_zone_hysteresis(None, present_observed=True)

        assert service._last_zone == ZONE_COUCH
        assert service._last_zone_at is not None
        assert service._last_zone_at > old

    def test_sustained_absence_clear_drops_committed_couch(self):
        from datetime import datetime, timezone

        from backend.services.camera_service import ZONE_COUCH

        service = _make_service()
        service._last_zone = ZONE_COUCH
        service._last_zone_at = datetime.now(timezone.utc)

        service._clear_committed_zone_posture("absent threshold")

        assert service._last_zone is None
        assert service._last_zone_at is None
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None


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

    def test_posture_cleared_when_zone_is_desk(self):
        """Fix B: desk zone occludes hips behind monitor/chair; MediaPipe
        extrapolates them at chest level → false reclined. No automation
        rule consumes desk+posture, so the cleanest fix is to clear any
        committed posture whenever the user is in the desk zone. Bed-zone
        observations remain the only source of committed posture."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "desk"
        service._last_posture = "reclined"  # Stale from a prior bed observation.
        service._last_posture_at = old
        service._candidate_posture = "upright"
        service._candidate_posture_since = old

        service._apply_posture_hysteresis("reclined")

        assert service._last_posture is None
        assert service._last_posture_at is None
        assert service._candidate_posture is None
        assert service._candidate_posture_since is None

    def test_posture_preserved_when_zone_is_bed(self):
        """Regression check for Fix B: the desk-clear branch must not
        leak into the bed zone — bed-zone observations are the entire
        point of the posture pipeline."""
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        service._last_zone = "bed"
        service._last_posture = "reclined"
        service._last_posture_at = old

        service._apply_posture_hysteresis("reclined")

        # Steady-state refresh path applied — posture preserved, timestamp bumped.
        assert service._last_posture == "reclined"
        assert service._last_posture_at is not None
        assert service._last_posture_at > old

    @pytest.mark.asyncio
    async def test_maybe_notify_fires_on_zone_transition(self):
        """When _last_zone transitions None → "bed" between calls,
        the helper must invoke automation.notify_camera_commit() exactly
        once. Repro of the 2026-05-08 01:35 EDT regression where
        zone/posture committed late after a restart and the engine
        had no signal to re-evaluate the overlay."""
        automation = AsyncMock()
        service = _make_service(automation=automation)

        zone_before = service._last_zone  # None
        service._last_zone = "bed"  # Simulate a hysteresis-driven commit.

        await service._maybe_notify_camera_commit(
            zone_before=zone_before,
            posture_before=service._last_posture,
        )

        automation.notify_camera_commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maybe_notify_fires_on_posture_transition(self):
        """Same for posture."""
        automation = AsyncMock()
        service = _make_service(automation=automation)

        posture_before = service._last_posture  # None
        service._last_posture = "reclined"

        await service._maybe_notify_camera_commit(
            zone_before=service._last_zone,
            posture_before=posture_before,
        )

        automation.notify_camera_commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maybe_notify_dedups_when_both_commit_same_frame(self):
        """If zone AND posture both commit in the same poll, only fire
        the notification once — re-applying the lights twice would
        burn dedup-cache + bridge writes for no benefit."""
        automation = AsyncMock()
        service = _make_service(automation=automation)

        service._last_zone = "bed"
        service._last_posture = "reclined"

        await service._maybe_notify_camera_commit(
            zone_before=None, posture_before=None,
        )

        automation.notify_camera_commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maybe_notify_skips_steady_state_refresh(self):
        """Same value before and after = steady-state refresh of the
        timestamp only. The overlay's output won't change so we MUST
        NOT trigger a re-apply (would amplify any write churn)."""
        automation = AsyncMock()
        service = _make_service(automation=automation)
        service._last_zone = "bed"
        service._last_posture = "reclined"

        # Both values unchanged from before → no transition, no notify.
        await service._maybe_notify_camera_commit(
            zone_before="bed", posture_before="reclined",
        )

        automation.notify_camera_commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_notify_skips_clear_to_none(self):
        """A commit being cleared (e.g. user left, ABSENT_THRESHOLD hit
        and clear_committed wiped the state) shouldn't fire a re-apply
        — the overlay just no-ops on missing zone/posture, so writing
        again with the no-overlay state is wasted work."""
        automation = AsyncMock()
        service = _make_service(automation=automation)
        # Post-clear state: was "bed", now None.
        service._last_zone = None
        service._last_posture = None

        await service._maybe_notify_camera_commit(
            zone_before="bed", posture_before="reclined",
        )

        automation.notify_camera_commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_notify_handles_missing_engine_method(self):
        """Older engines / test stubs may not implement
        notify_camera_commit. The helper must degrade gracefully."""
        # Plain MagicMock → notify_camera_commit auto-resolves to another
        # MagicMock. Use an object that explicitly lacks the attribute.
        class _BareAuto:
            pass

        service = _make_service(automation=_BareAuto())
        service._last_zone = "bed"

        # Should not raise.
        await service._maybe_notify_camera_commit(
            zone_before=None, posture_before=None,
        )

    @pytest.mark.asyncio
    async def test_maybe_notify_swallows_engine_exceptions(self):
        """If the engine call raises, the camera poll must keep going —
        the camera is the system's eyes; one failed re-apply must not
        kill the freshness loop."""
        automation = AsyncMock()
        automation.notify_camera_commit.side_effect = RuntimeError("boom")
        service = _make_service(automation=automation)
        service._last_zone = "bed"

        # Should not raise.
        await service._maybe_notify_camera_commit(
            zone_before=None, posture_before=None,
        )

        automation.notify_camera_commit.assert_awaited_once()

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
# Posture classification (Fix A — visibility floor + anatomical guard)
# ---------------------------------------------------------------------------


def _mock_pose_result(
    *,
    shoulder_y: float,
    shoulder_vis: float = 0.99,
    hip_y: float,
    hip_vis: float = 0.99,
):
    """Build a fake pose_result populating only the 4 torso landmarks
    `_evaluate_posture` actually reads (shoulders + hips)."""
    Landmark = namedtuple("Landmark", ["y", "visibility"])
    lms = [Landmark(0.0, 0.0)] * 25
    lms[11] = Landmark(shoulder_y, shoulder_vis)  # POSE_LEFT_SHOULDER
    lms[12] = Landmark(shoulder_y, shoulder_vis)  # POSE_RIGHT_SHOULDER
    lms[23] = Landmark(hip_y, hip_vis)            # POSE_LEFT_HIP
    lms[24] = Landmark(hip_y, hip_vis)            # POSE_RIGHT_HIP
    result = MagicMock()
    result.pose_landmarks = [lms]
    return result


class TestEvaluatePosture:
    """Hip-visibility floor (Fix A) rejects MediaPipe's extrapolated
    occluded landmarks; the anatomical-delta floor catches collapsed
    cases that slip past visibility. Together they kill the
    desk-83%-reclined false-classification observed 2026-05-17."""

    def test_visible_upright_returns_upright(self):
        """Regression: full visibility + healthy delta still works."""
        service = _make_service()
        pose = _mock_pose_result(shoulder_y=0.30, hip_y=0.55)  # delta=0.25
        assert service._evaluate_posture(pose) == "upright"

    def test_visible_reclined_returns_reclined(self):
        """Regression: full visibility + small-but-anatomical delta still
        classifies reclined (Anthony's empirical ~0.05 baseline)."""
        service = _make_service()
        pose = _mock_pose_result(shoulder_y=0.40, hip_y=0.47)  # delta=0.07
        assert service._evaluate_posture(pose) == "reclined"

    def test_low_hip_visibility_returns_none(self):
        """Fix A: hip visibility 0.6 falls below MIN_POSE_VISIBILITY_HIP
        (0.8). Even though delta would classify reclined, treating an
        extrapolated landmark as a real observation is the bug we're
        fixing — return None and let hysteresis preserve the prior."""
        service = _make_service()
        pose = _mock_pose_result(
            shoulder_y=0.40, shoulder_vis=0.99,
            hip_y=0.45, hip_vis=0.6,  # below 0.8 floor
        )
        assert service._evaluate_posture(pose) is None

    def test_collapsed_delta_returns_none(self):
        """Fix A: extrapolated occluded hips can clear the visibility
        floor but produce a near-zero delta (chest-level placement).
        The anatomical floor (0.05) rejects these as geometrically
        implausible."""
        service = _make_service()
        pose = _mock_pose_result(shoulder_y=0.40, hip_y=0.42)  # delta=0.02
        assert service._evaluate_posture(pose) is None

    def test_inverted_geometry_returns_none(self):
        """Fix A: hip Y above shoulder Y (negative delta) is a model
        error, not a posture. Return None."""
        service = _make_service()
        pose = _mock_pose_result(shoulder_y=0.50, hip_y=0.40)  # delta=-0.10
        assert service._evaluate_posture(pose) is None


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
        cap = MagicMock()
        cap.isOpened.return_value = True
        service._cap = cap

        await service.on_mode_change("sleeping")
        assert service._paused is True
        # on_mode_change nulls _cap and hands the old handle to an executor
        # for release — so assert on the captured reference, not service._cap.
        assert service._cap is None
        cap.release.assert_called_once()

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
        service._last_detection = "present"
        service._last_detection_at = datetime.now(timezone.utc)
        service._last_confidence = 0.9
        service._last_detection_source = "face"
        service._face_anchor_at["couch"] = datetime.now(timezone.utc)
        invalidated = []
        service.register_observation_invalidation_callback(invalidated.append)

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
        assert service._last_detection == "unknown"
        assert service._last_detection_at is None
        assert service._last_confidence == 0.0
        assert service._last_detection_source is None
        assert service._face_anchor_at == {}
        assert invalidated == ["latitude"]


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

    @pytest.mark.asyncio
    async def test_recover_capture_releases_old_and_reopens(self):
        """_recover_capture hands the wedged handle off for release and installs a fresh one.

        Release + reopen run off-loop in ``_open_capture_async`` (which calls
        ``_release_and_open`` in an executor). We stub that boundary so the
        test exercises recovery wiring without real hardware, and assert the
        old handle was passed in for release.
        """
        service = _make_service()
        old_cap = MagicMock()
        service._cap = old_cap
        fresh_cap = MagicMock()

        async def fake_open(*, release_first=None):
            # Mirror the real _release_and_open: release the prior handle.
            if release_first is not None:
                release_first.release()
            return fresh_cap

        with patch.object(service, "_open_capture_async", side_effect=fake_open):
            await service._recover_capture()

        old_cap.release.assert_called_once()
        assert service._cap is fresh_cap

    @pytest.mark.asyncio
    async def test_recover_capture_reopen_failure_leaves_cap_none(self):
        """If the off-loop reopen fails (watchdog timeout → None), _cap stays None.

        _process_frame short-circuits on a None cap, so leaving it None is the
        correct degraded state until a later poll succeeds.
        """
        service = _make_service()
        old_cap = MagicMock()
        service._cap = old_cap

        async def fake_open(*, release_first=None):
            return None

        with patch.object(service, "_open_capture_async", side_effect=fake_open):
            await service._recover_capture()

        assert service._cap is None

    @pytest.mark.asyncio
    async def test_poll_loop_recovers_from_frame_timeout(self, monkeypatch):
        """A hung _process_frame trips the watchdog, triggers recovery, loop continues."""
        from backend.services import camera_service as cam_module

        # Shrink the timeout so the test doesn't sleep 5s.
        monkeypatch.setattr(cam_module, "FRAME_READ_TIMEOUT_S", 0.05)
        monkeypatch.setattr(cam_module, "POLL_INTERVAL", 0)

        from datetime import datetime, timedelta, timezone

        from backend.services.camera_service import ZONE_COUCH, ZONE_HYSTERESIS_SECONDS

        service = _make_service()
        service._enabled = True
        service._cap = MagicMock()  # truthy; _process_frame won't actually run
        service._candidate_zone = ZONE_COUCH
        service._candidate_zone_since = datetime.now(timezone.utc) - timedelta(
            seconds=ZONE_HYSTERESIS_SECONDS + 1,
        )
        service._consecutive_absent = 2

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
        assert service._candidate_zone is None
        assert service._candidate_zone_since is None
        assert service._consecutive_absent == 2


# ---------------------------------------------------------------------------
# Face-anchor gate on pose-only present commits (Phase 2, 2026-05-21)
# ---------------------------------------------------------------------------


def _mock_full_pose_landmarks_result(
    visibility: float = 0.95,
    landmark_count: int = 5,
    x_positions: list[float] | None = None,
):
    """Construct a MediaPipe-style pose_landmarker result.

    By default sets all 5 torso landmarks (nose, both shoulders, both hips)
    at high visibility — the exact pattern that fires on the empty office
    chair (2026-05-21 truth-table walk).
    """
    import numpy as np

    def landmark(x: float, y: float, vis: float) -> MagicMock:
        return MagicMock(x=x, y=y, visibility=vis)
    # Indices: nose=0, left_shoulder=11, right_shoulder=12,
    # left_hip=23, right_hip=24. Fill 25 slots so the indexing in
    # _process_frame's pose_zone math doesn't IndexError.
    if x_positions is None:
        # Desk side (x < 0.40)
        x_positions = [0.30] * 5
    landmarks = [landmark(0.5, 0.5, 0.0)] * 25
    landmarks[0] = landmark(x_positions[0], 0.30, visibility)
    landmarks[11] = landmark(x_positions[1], 0.45, visibility)
    landmarks[12] = landmark(x_positions[2], 0.45, visibility)
    landmarks[23] = landmark(x_positions[3], 0.70, visibility)
    landmarks[24] = landmark(x_positions[4], 0.70, visibility)
    result = MagicMock()
    result.pose_landmarks = [landmarks]
    return result


class TestFaceAnchorPoseGate:
    """Pose-only present commits require a recent face anchor in the same
    zone — distinguishes the user from the empty office chair, whose
    torso-symmetric shape fires MediaPipe pose at 0.98 confidence.
    """

    def _service_with_pose_no_face(self):
        """Build a service where face detector returns nothing + pose fires."""
        service = _make_service()
        service._enabled = True

        import numpy as np
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((240, 320, 3), dtype=np.uint8))
        service._cap = mock_cap

        # No face detections
        mock_face_detector = MagicMock()
        mock_face_results = MagicMock()
        mock_face_results.detections = []
        mock_face_detector.detect.return_value = mock_face_results
        service._face_detector = mock_face_detector

        # Pose fires at 0.95 with all 5 landmarks at desk-side X
        mock_pose_landmarker = MagicMock()
        mock_pose_landmarker.detect.return_value = _mock_full_pose_landmarks_result()
        service._pose_landmarker = mock_pose_landmarker
        return service

    def test_pose_only_no_anchor_does_not_commit_present(self):
        """The empty-chair scenario: pose fires at 0.95 with full landmarks,
        but no face anchor exists. Should NOT commit present.
        """
        service = self._service_with_pose_no_face()
        result = service._process_frame()
        assert result is not None
        # Falls through to absent (no face, no anchor → no commit from pose)
        assert result["status"] == "absent"
        assert result["source"] is None

    def test_pose_with_fresh_face_anchor_commits_present(self):
        """User sat down (face detected → anchor set), then turned to side
        monitor (face gone, pose still firing). Should keep committing
        present via pose since the anchor is fresh.
        """
        service = self._service_with_pose_no_face()
        # Seed a fresh face anchor for the couch zone (the single living-room
        # zone the camera emits since the 2026-05-27 Latitude relocation).
        from datetime import datetime, timezone
        service._face_anchor_at["couch"] = datetime.now(timezone.utc)

        result = service._process_frame()
        assert result is not None
        assert result["status"] == "present"
        assert result["source"] == "pose"
        assert result["zone"] == "couch"

    def test_pose_with_stale_face_anchor_does_not_commit(self):
        """Anchor older than TTL → treated as expired. Pose falls through
        to absent like the no-anchor case.
        """
        from datetime import datetime, timedelta, timezone
        from backend.services.camera_service import FACE_ANCHOR_TTL_SECONDS

        service = self._service_with_pose_no_face()
        service._face_anchor_at["desk"] = (
            datetime.now(timezone.utc) - timedelta(seconds=FACE_ANCHOR_TTL_SECONDS + 5)
        )

        result = service._process_frame()
        assert result is not None
        assert result["status"] == "absent"

    def test_face_anchor_refreshes_on_qualifying_face(self):
        """Face detected with conf >= FACE_ANCHOR_MIN_CONFIDENCE → anchor
        timestamp updates for the face's zone.
        """
        from backend.services.camera_service import (
            FACE_ANCHOR_MIN_CONFIDENCE,
            FACE_TRUST_THRESHOLD,
        )

        service = _make_service()
        service._enabled = True

        import numpy as np
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((240, 320, 3), dtype=np.uint8))
        service._cap = mock_cap

        # Face in the couch zone, confidence just above the anchor threshold
        mock_face_detector = MagicMock()
        mock_face_results = MagicMock()
        mock_face_results.detections = [
            _mock_detection(FACE_ANCHOR_MIN_CONFIDENCE + 0.05, origin_x=50, width=60),
        ]
        mock_face_detector.detect.return_value = mock_face_results
        service._face_detector = mock_face_detector
        # No pose this frame
        service._pose_landmarker = None

        assert "couch" not in service._face_anchor_at
        result = service._process_frame()
        assert result["status"] == "present"
        assert result["zone"] is None
        assert FACE_ANCHOR_MIN_CONFIDENCE < result["confidence"] < FACE_TRUST_THRESHOLD
        assert "couch" in service._face_anchor_at

        service._apply_zone_hysteresis(
            result["zone"], present_observed=result["status"] == "present",
        )
        assert service._last_zone is None
        assert service._candidate_zone is None

    def test_face_below_anchor_threshold_does_not_refresh(self):
        """Weak chair-back faces (conf < FACE_ANCHOR_MIN_CONFIDENCE) must
        NOT refresh the anchor — that would defeat the gate's purpose.
        """
        from backend.services.camera_service import FACE_ANCHOR_MIN_CONFIDENCE

        service = _make_service()
        service._enabled = True

        import numpy as np
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((240, 320, 3), dtype=np.uint8))
        service._cap = mock_cap

        # Weak face — well below anchor threshold (chair-back range)
        mock_face_detector = MagicMock()
        mock_face_results = MagicMock()
        mock_face_results.detections = [
            _mock_detection(FACE_ANCHOR_MIN_CONFIDENCE - 0.10, origin_x=50, width=60),
        ]
        mock_face_detector.detect.return_value = mock_face_results
        service._face_detector = mock_face_detector
        service._pose_landmarker = None

        service._process_frame()
        assert "desk" not in service._face_anchor_at

    def test_pose_with_degraded_shoulders_commits_via_couch_anchor(self):
        """Degraded shoulder visibility (deep profile / bent forward) must not
        demote a real user to absent.

        Pre-2026-05-27 the camera split desk/bed by shoulder-center X, so
        sub-visibility shoulders left ``pose_zone`` ambiguous (None) and the
        gate fell back to the most-recent anchor in any zone. After the
        living-room relocation the camera emits a single ``ZONE_COUCH`` for any
        firing pose, so that fallback branch is now unreachable — pose always
        resolves to couch. This guards the surviving contract: a degraded-pose
        frame still fires and commits present when a fresh couch anchor exists.
        """
        from datetime import datetime, timezone

        service = self._service_with_pose_no_face()
        # Both shoulders below the visibility floor — pose still fires off the
        # remaining landmarks and resolves to the single couch zone.
        degraded_pose = _mock_full_pose_landmarks_result(visibility=0.95)
        degraded_pose.pose_landmarks[0][11].visibility = 0.1
        degraded_pose.pose_landmarks[0][12].visibility = 0.1
        service._pose_landmarker.detect.return_value = degraded_pose

        service._face_anchor_at["couch"] = datetime.now(timezone.utc)
        result = service._process_frame()
        assert result["status"] == "present"
        assert result["source"] == "pose"
        assert result["zone"] == "couch"

    def test_status_surfaces_face_anchor_age(self):
        """get_status() includes ``face_anchor_age_s_by_zone`` so dashboards
        and the truth-table walk can see when the anchor was last refreshed.
        """
        from datetime import datetime, timedelta, timezone

        service = _make_service()
        service._face_anchor_at["desk"] = (
            datetime.now(timezone.utc) - timedelta(seconds=12.0)
        )
        status = service.get_status()
        assert "face_anchor_age_s_by_zone" in status
        assert "face_anchor_ttl_s" in status
        assert status["face_anchor_age_s_by_zone"]["desk"] == pytest.approx(12.0, abs=1.0)


# ---------------------------------------------------------------------------
# Watchdog wedge-restart escalation (GH#73)
# ---------------------------------------------------------------------------
#
# ``camera_watchdog_loop`` must escalate to a process restart after
# ``CAMERA_WEDGE_RESTART_THRESHOLD`` consecutive failed respawns, regardless of
# whether spawn returned ``{"status": "error"}`` (the common
# cv2.VideoCapture-can't-open path) or raised (defense in depth).
# Locks the contract surfaced in GH#73 / commit f25e079.


def _watchdog_fake_app():
    app = MagicMock()
    app.state.camera_service = None
    app.state.automation.current_mode = "working"
    app.state.heartbeats = None
    app.state.ws_manager = AsyncMock()
    app.state.ws_manager.broadcast = AsyncMock()
    return app


def _patch_camera_enabled_setting(monkeypatch):
    from backend.api.routes import routines

    async def fake_load_setting(key, *args, **kwargs):
        if key == "camera_enabled":
            return {"enabled": True}
        return None

    monkeypatch.setattr(routines, "load_setting", fake_load_setting)


async def _drive_watchdog_until(predicate, monkeypatch, *, spawn_fn, timeout=5.0):
    """Drive ``camera_watchdog_loop`` until ``predicate()`` returns truthy
    or ``timeout`` elapses, then cancel cleanly. Returns ``escalation_calls``."""
    from backend.services import camera_service as cs

    monkeypatch.setattr(cs, "CAMERA_WATCHDOG_INTERVAL_SECONDS", 0.0)
    _patch_camera_enabled_setting(monkeypatch)
    monkeypatch.setattr(cs, "spawn_camera_service", spawn_fn)

    escalation_calls: list[str] = []

    async def fake_escalate(app, detail):
        escalation_calls.append(detail)
        return True

    monkeypatch.setattr(cs, "_escalate_camera_wedge_restart", fake_escalate)

    app = _watchdog_fake_app()
    task = asyncio.create_task(cs.camera_watchdog_loop(app))
    try:
        deadline_ticks = int(timeout / 0.01)
        for _ in range(deadline_ticks):
            if predicate():
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return escalation_calls


@pytest.mark.asyncio
async def test_watchdog_consecutive_open_failures_escalate(monkeypatch):
    """cv2 open failure path: spawn returns status=error each tick → escalation
    fires at the threshold."""
    from backend.services import camera_service as cs

    failed_spawns: list[str] = []

    async def fake_spawn(app, *, reason):
        failed_spawns.append(reason)
        return {
            "status": "error",
            "detail": "Camera unavailable (may be in use or missing)",
        }

    escalation_calls = await _drive_watchdog_until(
        predicate=lambda: len(failed_spawns) >= cs.CAMERA_WEDGE_RESTART_THRESHOLD,
        monkeypatch=monkeypatch,
        spawn_fn=fake_spawn,
    )
    await asyncio.sleep(0.05)  # Let the escalation tick land after threshold.

    assert len(failed_spawns) >= cs.CAMERA_WEDGE_RESTART_THRESHOLD
    assert len(escalation_calls) >= 1
    assert "consecutive failed respawns" in escalation_calls[0]
    assert "watchdog_no_service" in escalation_calls[0]


@pytest.mark.asyncio
async def test_watchdog_consecutive_spawn_exceptions_also_escalate(monkeypatch):
    """spawn raising an exception (not just returning status=error) must also
    feed the counter — otherwise a persistent wedge that surfaces as an
    exception (rather than a clean error return) could never escalate."""
    from backend.services import camera_service as cs

    spawn_calls: list[str] = []

    async def raising_spawn(app, *, reason):
        spawn_calls.append(reason)
        raise RuntimeError("simulated spawn failure")

    escalation_calls = await _drive_watchdog_until(
        predicate=lambda: len(spawn_calls) >= cs.CAMERA_WEDGE_RESTART_THRESHOLD,
        monkeypatch=monkeypatch,
        spawn_fn=raising_spawn,
    )
    await asyncio.sleep(0.05)

    assert len(spawn_calls) >= cs.CAMERA_WEDGE_RESTART_THRESHOLD
    assert len(escalation_calls) >= 1
    assert "consecutive failed respawns" in escalation_calls[0]


@pytest.mark.asyncio
async def test_watchdog_successful_respawn_resets_counter(monkeypatch):
    """A successful respawn must reset the consecutive-failure counter so a
    transient flap (fail → fail → ok → fail → fail) never accumulates the
    3-in-a-row that would trip escalation."""
    sequence = iter(
        [
            {"status": "error", "detail": "first fail"},
            {"status": "error", "detail": "second fail"},
            {"status": "ok", "detail": "recovered"},
            {"status": "error", "detail": "fourth fail"},
            {"status": "error", "detail": "fifth fail"},
        ]
    )
    spawn_calls: list[str] = []

    async def fake_spawn(app, *, reason):
        spawn_calls.append(reason)
        try:
            return next(sequence)
        except StopIteration:
            return {"status": "ok", "detail": "exhausted"}

    escalation_calls = await _drive_watchdog_until(
        predicate=lambda: len(spawn_calls) >= 5,
        monkeypatch=monkeypatch,
        spawn_fn=fake_spawn,
    )
    await asyncio.sleep(0.05)

    assert len(spawn_calls) >= 5
    assert escalation_calls == []
