"""Camera presence detection — MediaPipe face + pose on the Latitude webcam.

Captures one frame every ``POLL_INTERVAL`` seconds, runs MediaPipe Face
Detection first, and falls back to MediaPipe Pose Landmarker when face
detection misses. Reports presence/absence to the automation engine and
measures ambient light level from frame luminance.

The pose fallback exists because the Latitude sits in a corner ~2–3m from
the desk; the user spends most working sessions in deep three-quarter
profile toward the monitor, which BlazeFace (even full-range) scores
unreliably. Body pose is invariant to head angle at that distance.

Phase 2a: Presence via face OR pose (~5ms face, ~25ms pose-on-miss).
Phase 2b: Posture classification (upright vs reclined) from the same pose
    landmarks — expose-only (published via status / WS / ml_decisions, no
    automation behavior consumes it yet).

Privacy guarantees:
  - Frames are numpy arrays in memory only, overwritten each cycle.
  - Frames never touch disk, network, logs, or any API response.
  - Only derived labels (present/absent), confidence, detection source,
    and lux values persist. Pose landmark coordinates stay in-process.
  - Opt-in via camera_enabled app setting (default false).
  - Dell Latitude camera LED activates when capturing (hardware-enforced).
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("home_hub.camera")

# Polling and detection constants
POLL_INTERVAL = 2       # Seconds between frame captures
# 640x480 gives BlazeFace enough pixel detail to score Anthony's profile view
# at 2-3m (corner position) noticeably higher than 320x240 did. Pose landmarker
# was already solid at the lower resolution; face scores are the beneficiary.
# Lux calibration (exposure + baseline_lux) MUST be re-run after any change to
# these constants — gray.mean() at the new pixel count will differ from the
# value the stored baseline was recorded at.
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
# Fifteen consecutive misses (~30s) before flipping to away. Extended past
# the original seven (~14s) after a live low-light scenario (reading in bed
# at ema_lux ~30, 20% of baseline) showed face/pose detection flapping 25-40%
# and the mode flipping to away on brief misses. Brief dropouts in dim light
# are the common case, not the exception, so we want more dampening.
ABSENT_THRESHOLD = 15
# Full-range BlazeFace returns noticeably lower scores than short-range at our
# corner-view working distance (~2–3m, three-quarter profile toward the
# monitor). Snapshot sampling showed hits at 0.38 confidence and misses
# sharing the same pose — the score sits in the 0.2–0.4 range. Loosened to
# 0.15 from 0.2 after low-light bed scenario (ema_lux 31 vs baseline 148)
# showed face model only clearing 0.2 intermittently. Pip-level flicker is
# dampened by the larger ABSENT_THRESHOLD above. Fixed corner view has no
# other face-like regions (bed / wall art) that false-trigger at this score.
MIN_FACE_CONFIDENCE = 0.15
# Pose fallback — MediaPipe Pose Landmarker (Tasks API). Declares "present"
# when enough torso landmarks (nose, shoulders, hips) are visible above
# MIN_POSE_VISIBILITY. This catches Anthony at the desk in deep profile,
# where BlazeFace scores are too noisy to rely on alone.
MIN_POSE_VISIBILITY = 0.5
POSE_MIN_LANDMARKS = 3
# BlazePose landmark indices for the torso skeleton. See:
# https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker#pose_landmarker_model
POSE_NOSE = 0
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12
POSE_LEFT_HIP = 23
POSE_RIGHT_HIP = 24
POSE_TORSO_INDICES = (
    POSE_NOSE, POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER,
    POSE_LEFT_HIP, POSE_RIGHT_HIP,
)
# Edges drawn between landmarks in snapshot annotations (stick-figure torso).
POSE_SKELETON_EDGES = (
    (POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER),
    (POSE_LEFT_SHOULDER, POSE_LEFT_HIP),
    (POSE_RIGHT_SHOULDER, POSE_RIGHT_HIP),
    (POSE_LEFT_HIP, POSE_RIGHT_HIP),
    (POSE_NOSE, POSE_LEFT_SHOULDER),
    (POSE_NOSE, POSE_RIGHT_SHOULDER),
)

# Zone mapping — the Latitude's corner view splits the bedroom into two
# semantic zones along the horizontal axis: the desk (left ~1/3 of frame)
# where working / gaming / watching happen, and the bed (right ~2/3) where
# relax / sleeping happen. The detected person's center-X (from face bbox
# or pose torso) is classified against ZONE_DESK_THRESHOLD.
#
# Expose-only in this pass — zone is published to status / WebSocket /
# ML logger but no automation behavior consumes it yet.
ZONE_DESK = "desk"
ZONE_BED = "bed"
# Normalized X (detected center / frame width). Corner view places desk
# around ~0.15 and bed roughly 0.4–0.9; 0.40 catches the accent-chair
# transition region. Hysteresis (below) absorbs brief crossings.
ZONE_DESK_THRESHOLD = 0.40
# A new candidate zone must hold this many seconds before it replaces the
# committed zone. 15s matches the "sustained detection" character of the
# absent threshold (7 frames × 2s poll ≈ 14s).
ZONE_HYSTERESIS_SECONDS = 15

# Posture classification — derived from pose landmarks when the pose path
# fires. Compares mean shoulder-Y to mean hip-Y in MediaPipe's normalized
# 0–1 coordinate space (Y=0 top, Y=1 bottom): upright torsos sit vertically
# on-screen (hips below shoulders), reclined torsos collapse that delta
# toward zero. Face-path hits and absent frames emit posture=None (hips
# are not available) — hysteresis preserves the last committed value
# through brief blanks, so a face-only session doesn't erase a prior
# upright/reclined commit.
#
# Expose-only: published via status / WebSocket / ml_decisions, no
# automation behavior consumes it yet. Future use: zone + posture gate
# for mode-transition actuation (e.g. zone=bed + reclined sustained →
# nudge toward relax, while carving out the watch-projector-from-bed
# pattern where zone=bed but posture is upright).
POSTURE_UPRIGHT = "upright"
POSTURE_RECLINED = "reclined"
# Minimum (hip_y - shoulder_y) in normalized coords to classify upright.
# For Anthony at 2–3m in profile, typical uprights produce ~0.20 and
# reclined ~0.05 — 0.12 splits the distribution cleanly.
POSTURE_UPRIGHT_MIN_DELTA = 0.12
# Hysteresis mirrors the zone rule (15s sustained before commit).
POSTURE_HYSTERESIS_SECONDS = 15

# Ambient lux calibration constants. Auto-exposure is disabled when a
# calibration is present so gray.mean() reflects actual room brightness
# instead of the webcam compensating with its aperture.
EXPOSURE_TARGET_LUX = 100   # Target frame mean at calibration time
EXPOSURE_TOLERANCE = 10     # Accept calibration within target ± tolerance
CALIBRATION_FRAMES = 10     # Frames averaged per exposure probe
LUX_EMA_ALPHA = 0.3         # Smoothing factor (α*raw + (1-α)*ema) — ~20s to 95%
LUX_CALIBRATION_SETTING_KEY = "lux_calibration_config"
# OpenCV DirectShow/V4L2 auto-exposure magic numbers:
#   0.25 = manual exposure, 0.75 = auto (on Windows DShow backend)
CAP_AUTO_EXPOSURE_MANUAL = 0.25

# Model files for MediaPipe Tasks API (v0.10.20+).
# Using the full-range BlazeFace model: the Latitude dashboard sits in a
# corner ~2–3m from Anthony at the desk, past the short-range model's
# comfortable detection envelope (<2m, frontal-preferred). The full-range
# variant keeps faces in the frame under three-quarter profile toward the
# monitor, which is the dominant pose during working mode.
MODEL_DIR = Path("data/models")
MODEL_FILENAME = "blaze_face_full_range.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_detector/blaze_face_full_range/float16/latest/"
    "blaze_face_full_range.tflite"
)
# Pose Landmarker (lite variant ≈ 5 MB). Runs only when face detection
# misses in the poll loop, and always during snapshot annotation.
POSE_MODEL_FILENAME = "pose_landmarker_lite.task"
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)


class CameraService:
    """MediaPipe-based camera presence detection for the Latitude webcam.

    Runs inside the FastAPI process. Blocking OpenCV/MediaPipe calls are
    dispatched to the default thread pool via ``asyncio.run_in_executor``.
    """

    def __init__(
        self,
        ws_manager: Any,
        automation_engine: Any,
        ml_logger: Any = None,
    ) -> None:
        self._ws_manager = ws_manager
        self._automation = automation_engine
        self._ml_logger = ml_logger

        self._enabled = False
        self._paused = False  # Paused during sleeping mode
        self._cap = None
        self._cap_lock = threading.Lock()  # Serializes poll-loop and snapshot reads
        self._face_detector = None
        self._pose_landmarker = None

        # Detection state
        self._consecutive_absent: int = 0
        self._last_detection: str = "unknown"
        self._last_detection_at: Optional[datetime] = None
        self._last_confidence: float = 0.0
        self._last_detection_source: Optional[str] = None  # "face" | "pose" | None
        self._last_ambient_lux: float = 0.0
        self._was_absent: bool = False

        # Zone mapping — committed zone + pending-candidate state (hysteresis).
        # ``_last_zone_at`` records when the current commit was made so
        # consumers (e.g. _apply_zone_overlay) can ignore stale values that
        # outlived a long absence — the overlay reads ``camera.zone`` directly
        # and would otherwise honor a commit from hours ago.
        self._last_zone: Optional[str] = None            # "desk" | "bed" | None
        self._last_zone_at: Optional[datetime] = None
        self._candidate_zone: Optional[str] = None       # pending zone awaiting commit
        self._candidate_zone_since: Optional[datetime] = None

        # Posture classification — same hysteresis pattern as zone.
        self._last_posture: Optional[str] = None         # "upright" | "reclined" | None
        self._last_posture_at: Optional[datetime] = None
        self._candidate_posture: Optional[str] = None
        self._candidate_posture_since: Optional[datetime] = None

        # Heartbeat registry — set via set_heartbeat_registry from lifespan.
        # Camera is opt-in, so we register only on enable and deregister on
        # disable / pause to avoid false-flagging legitimate downtime.
        self._heartbeat = None

        # Ambient lux calibration + smoothing
        self._calibrated: bool = False
        self._exposure_value: Optional[float] = None
        self._baseline_lux: Optional[float] = None
        self._ema_lux: Optional[float] = None
        self._last_lux_update: Optional[datetime] = None
        self._calibrating: bool = False

    @property
    def enabled(self) -> bool:
        """Whether the camera service is active and polling."""
        return self._enabled

    async def start(self) -> None:
        """Open the webcam and initialize MediaPipe face + pose models.

        Fails gracefully if the camera is unavailable (busy, missing, etc.).
        Downloads the face detection model on first run (~1 MB) and the
        pose landmarker model (~5 MB). Pose init is best-effort — if it
        fails the service falls back to face-only detection.
        """
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            logger.warning(
                "Cannot start camera service — missing dependency: %s", exc
            )
            return

        # Open webcam (device 0 = built-in camera on Latitude)
        try:
            self._cap = cv2.VideoCapture(0)
            if not self._cap.isOpened():
                logger.warning(
                    "Camera service: webcam not available "
                    "(may be in use by another process)"
                )
                self._cap = None
                return

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            await self._load_calibration()
        except Exception as exc:
            logger.error("Failed to open webcam: %s", exc, exc_info=True)
            self._cap = None
            return

        # Ensure face detection model is available
        face_model_path = MODEL_DIR / MODEL_FILENAME
        if not face_model_path.exists():
            if not self._download_model(face_model_path, MODEL_URL, "face detection"):
                if self._cap:
                    self._cap.release()
                    self._cap = None
                return

        # Initialize MediaPipe Face Detection (Tasks API, v0.10.20+)
        try:
            BaseOptions = mp.tasks.BaseOptions
            FaceDetector = mp.tasks.vision.FaceDetector
            FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions

            options = FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(face_model_path)),
                min_detection_confidence=MIN_FACE_CONFIDENCE,
            )
            self._face_detector = FaceDetector.create_from_options(options)
        except Exception as exc:
            logger.error(
                "Failed to initialize MediaPipe face detection: %s",
                exc,
                exc_info=True,
            )
            if self._cap:
                self._cap.release()
                self._cap = None
            return

        # Initialize MediaPipe Pose Landmarker (fallback for profile views).
        # Best-effort: if this fails, we stay face-only.
        pose_model_path = MODEL_DIR / POSE_MODEL_FILENAME
        if not pose_model_path.exists():
            if not self._download_model(pose_model_path, POSE_MODEL_URL, "pose"):
                logger.warning(
                    "Pose model unavailable — continuing with face-only detection"
                )
                pose_model_path = None

        if pose_model_path is not None:
            try:
                PoseLandmarker = mp.tasks.vision.PoseLandmarker
                PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
                pose_options = PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(pose_model_path)),
                    num_poses=1,
                    min_pose_detection_confidence=0.5,
                    min_pose_presence_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                self._pose_landmarker = PoseLandmarker.create_from_options(pose_options)
                logger.info("Pose landmarker initialized (fallback for face-miss frames)")
            except Exception as exc:
                logger.warning(
                    "Pose landmarker init failed — continuing with face-only: %s",
                    exc,
                )
                self._pose_landmarker = None

        self._enabled = True
        if self._heartbeat is not None:
            self._heartbeat.register("camera", float(POLL_INTERVAL))
        logger.info("Camera presence detection started (polling every %ds)", POLL_INTERVAL)

    @staticmethod
    def _download_model(model_path: Path, url: str, label: str) -> bool:
        """Download a MediaPipe model asset from the given URL.

        Args:
            model_path: Filesystem destination (parent is mkdir'd).
            url: HTTPS URL of the model file.
            label: Human-readable name for log messages (e.g. "face detection").

        Returns:
            True if download succeeded.
        """
        try:
            import httpx

            model_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Downloading %s model...", label)
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                model_path.write_bytes(resp.content)
            logger.info(
                "%s model saved (%d bytes)", label.capitalize(), len(resp.content)
            )
            return True
        except Exception as exc:
            logger.error("Failed to download %s model: %s", label, exc)
            return False

    async def _load_calibration(self) -> None:
        """Load persisted exposure calibration and apply it to the webcam.

        If no calibration exists, auto-exposure stays on and ambient_lux is
        effectively uncalibrated (the room-brightness signal compresses to
        ~80–140 regardless of actual conditions). The automation engine's
        lux multiplier guards against this via the ``calibrated`` flag.
        """
        from backend.api.routes.routines import load_setting

        config = await load_setting(LUX_CALIBRATION_SETTING_KEY)
        if not config or "exposure_value" not in config:
            logger.warning(
                "Ambient lux uncalibrated — POST /api/camera/calibrate to enable "
                "brightness adaptation (working / relax modes)"
            )
            return

        try:
            import cv2
            exposure = float(config["exposure_value"])
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, CAP_AUTO_EXPOSURE_MANUAL)
            self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            self._exposure_value = exposure
            baseline = config.get("baseline_lux")
            self._baseline_lux = float(baseline) if baseline is not None else None
            self._calibrated = True
            logger.info(
                "Applied lux calibration: exposure=%.2f, baseline_lux=%s",
                exposure,
                f"{self._baseline_lux:.1f}" if self._baseline_lux is not None else "unset",
            )
        except Exception as exc:
            logger.error("Failed to apply lux calibration: %s", exc, exc_info=True)

    async def calibrate_exposure(self) -> dict:
        """Binary-search webcam exposure until gray.mean() ≈ EXPOSURE_TARGET_LUX.

        Runs the blocking OpenCV loop in a thread pool. Persists the discovered
        exposure value to ``app_settings`` under ``lux_calibration_config`` so
        subsequent service restarts can re-apply it without re-calibrating.

        Returns:
            ``{status, exposure_value, measured_lux, detail}``.
        """
        if not self._enabled or self._cap is None or not self._cap.isOpened():
            return {"status": "error", "detail": "camera not available"}
        if self._paused:
            return {"status": "error", "detail": "camera paused (sleeping mode)"}
        if self._calibrating:
            return {"status": "error", "detail": "calibration already in progress"}

        self._calibrating = True
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._calibrate_exposure_sync)
            if result.get("status") != "ok":
                return result

            from backend.api.routes.routines import save_setting

            now = datetime.now(timezone.utc).isoformat()
            baseline = float(result["measured_lux"])
            await save_setting(
                LUX_CALIBRATION_SETTING_KEY,
                {
                    "exposure_value": result["exposure_value"],
                    "target_lux": EXPOSURE_TARGET_LUX,
                    "baseline_lux": baseline,
                    "calibrated_at": now,
                },
            )
            self._exposure_value = result["exposure_value"]
            self._baseline_lux = baseline
            # Reset EMA to the fresh baseline so the multiplier reports 1.00
            # immediately. Without this reset, the smoothed value keeps
            # decaying from the previous calibration's readings for ~2 min,
            # showing a spurious modulation while the math catches up.
            self._ema_lux = baseline
            self._last_lux_update = datetime.now(timezone.utc)
            self._calibrated = True
            logger.info(
                "Calibration complete: exposure=%.2f, baseline_lux=%.1f",
                result["exposure_value"],
                baseline,
            )
            return result
        finally:
            self._calibrating = False

    def _calibrate_exposure_sync(self) -> dict:
        """Blocking calibration. Runs in executor.

        Iteratively picks a fixed exposure value that produces a steady-state
        ``gray.mean()`` reading near the target, then records the actual
        steady-state mean as the baseline. The measurement cadence intentionally
        mirrors the live ``poll_loop`` (sleep between reads, single-frame
        captures) so the recorded baseline reflects what live polling will
        actually see — burst reads were inflating prior calibrations because
        the webcam's auto-gain wound up high during rapid frame reads but
        settled back down between sparse live polls.
        """
        import time

        import cv2

        # Switch to manual exposure so our writes take effect.
        self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, CAP_AUTO_EXPOSURE_MANUAL)

        # Sensible DShow exposure range — staying inside the driver's normal
        # bounds avoids the over-dark territory (~-20+) where the sensor is
        # at its noise floor and dynamic range collapses.
        EXPOSURE_MIN = -12.0
        EXPOSURE_MAX = 0.0
        ACCEPT_LO, ACCEPT_HI = 60.0, 180.0  # Range we'll stop searching in
        AGC_SETTLE_S = 3.0                  # Sleep so auto-gain reaches idle
        FRAME_INTERVAL_S = 0.5              # Spacing between baseline frames
        BASELINE_FRAMES = 3

        def steady_measure(exposure: float) -> float:
            """Set exposure, wait for AGC, take a poll-cadence measurement."""
            self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            time.sleep(AGC_SETTLE_S)
            self._cap.read()  # Drop the first frame after settle
            readings: list[float] = []
            for _ in range(BASELINE_FRAMES):
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    readings.append(float(gray.mean()))
                time.sleep(FRAME_INTERVAL_S)
            if not readings:
                return -1.0
            return sum(readings) / len(readings)

        # Start at a sensible middle and adjust by ±2 stops until the steady
        # reading sits in [60, 180]. Worst case: 6 attempts × ~5s = 30s.
        exposure = -6.0
        measured = -1.0
        for _ in range(6):
            measured = steady_measure(exposure)
            if measured < 0:
                return {"status": "error", "detail": "camera read failed"}
            if ACCEPT_LO <= measured <= ACCEPT_HI:
                break
            # Adjust toward target. Each ±2 roughly halves/doubles brightness.
            if measured > ACCEPT_HI:
                exposure -= 2.0
            else:
                exposure += 2.0
            exposure = max(EXPOSURE_MIN, min(EXPOSURE_MAX, exposure))

        return {
            "status": "ok",
            "exposure_value": exposure,
            "measured_lux": measured,
            "detail": (
                f"calibrated: exposure={exposure:.2f}, "
                f"baseline_lux={measured:.1f}"
            ),
        }

    def _update_ema_lux(self, raw_lux: float) -> None:
        """Update exponential moving average of ambient lux (α=0.1)."""
        if self._ema_lux is None:
            self._ema_lux = raw_lux
        else:
            self._ema_lux = LUX_EMA_ALPHA * raw_lux + (1 - LUX_EMA_ALPHA) * self._ema_lux
        self._last_lux_update = datetime.now(timezone.utc)

    @property
    def ema_lux(self) -> Optional[float]:
        """Smoothed ambient lux reading, or None if no calibration / no data."""
        if not self._calibrated:
            return None
        return self._ema_lux

    @property
    def last_lux_update(self) -> Optional[datetime]:
        """UTC timestamp of the most recent lux read (used for staleness checks)."""
        return self._last_lux_update

    @property
    def baseline_lux(self) -> Optional[float]:
        """Calibrated "normal room" lux reading — center of the multiplier curve."""
        return self._baseline_lux

    @property
    def zone(self) -> Optional[str]:
        """Currently committed zone after hysteresis — 'desk' | 'bed' | None.

        None when no zone has yet committed (camera just started, or the user
        hasn't been detected yet). Brief absences preserve the committed zone;
        a sustained absence past ``ABSENT_THRESHOLD`` clears the commit.
        """
        return self._last_zone

    @property
    def zone_committed_at(self) -> Optional[datetime]:
        """UTC timestamp of the most recent zone commit (None if not yet committed).

        Consumers should treat older commits as missing — see
        ``AutomationEngine._apply_zone_overlay`` for the freshness gate.
        """
        return self._last_zone_at

    @property
    def posture(self) -> Optional[str]:
        """Currently committed posture after hysteresis — 'upright' | 'reclined' | None.

        None when no posture has yet committed (pose has never fired with
        visible hips). Face-only sessions and brief pose misses preserve the
        committed value; sustained absence past ``ABSENT_THRESHOLD`` clears it.
        """
        return self._last_posture

    @property
    def posture_committed_at(self) -> Optional[datetime]:
        """UTC timestamp of the most recent posture commit (None if not yet committed)."""
        return self._last_posture_at

    @property
    def last_detection(self) -> str:
        """Most recent detection status — 'present' | 'absent' | 'unknown'."""
        return self._last_detection

    @property
    def last_detection_at(self) -> Optional[datetime]:
        """UTC timestamp of the most recent detection update (any status).

        Consumers use this to decide whether ``last_detection`` is fresh
        enough to trust — e.g. presence_service vetoes a departure fade
        only if a 'present' reading landed within the last ~60s.
        """
        return self._last_detection_at

    def _build_fusion_factors(
        self,
        status: str,
        detection_source: Optional[str],
        confidence: float,
        multiplier: float,
    ) -> list[dict]:
        """Build the camera lane's sub-factors for the analytics constellation.

        Returns four pips: presence (face/pose/absent), zone, posture, and
        a lux band. Uses currently-committed hysteresis values so pips
        don't flicker on single-frame misses.
        """
        if status == "absent":
            presence_display = "absent"
            presence_impact = 0.3
        elif detection_source == "pose":
            presence_display = "pose"
            presence_impact = max(0.5, min(1.0, confidence))
        else:
            presence_display = detection_source or "face"
            presence_impact = max(0.6, min(1.0, confidence))

        factors: list[dict] = [
            {
                "key": "presence",
                "label": "Presence",
                "value": status,
                "display": presence_display,
                "impact": round(presence_impact, 3),
            },
        ]

        # Zone pip — only surface when we've actually committed a zone.
        if self._last_zone is not None:
            factors.append({
                "key": "zone",
                "label": "Zone",
                "value": self._last_zone,
                "display": self._last_zone,
                "impact": 0.8,
            })

        # Posture pip — only surface when pose has committed a value.
        if self._last_posture is not None:
            factors.append({
                "key": "posture",
                "label": "Posture",
                "value": self._last_posture,
                "display": self._last_posture,
                "impact": 0.7,
            })

        # Lux band pip — only meaningful after calibration.
        if self._calibrated and self._ema_lux is not None:
            if multiplier >= 1.08:
                lux_display = "dark"
                lux_impact = 1.0
            elif multiplier <= 0.92:
                lux_display = "bright"
                lux_impact = 1.0
            else:
                lux_display = "normal"
                lux_impact = 0.4
            factors.append({
                "key": "lux",
                "label": "Light",
                "value": round(float(self._ema_lux), 1),
                "display": lux_display,
                "impact": lux_impact,
            })

        return factors[:4]

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan).

        The registry is used by the poll loop to publish liveness; the
        camera registers itself only on enable / resume and deregisters
        on disable / pause so legitimate downtime isn't flagged stale.
        """
        self._heartbeat = registry

    async def poll_loop(self) -> None:
        """Background task — capture and classify one frame every POLL_INTERVAL seconds."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)

                if not self._enabled or self._paused:
                    continue
                if self._heartbeat is not None:
                    self._heartbeat.tick("camera")

                # Run blocking frame capture + inference in thread pool
                result = await loop.run_in_executor(None, self._process_frame)
                if result is None:
                    continue

                status = result["status"]
                confidence = result["confidence"]
                source = result.get("source")
                pose_landmark_count = result.get("pose_landmark_count", 0)
                ambient_lux = result["ambient_lux"]
                frame_zone = result.get("zone")
                frame_posture = result.get("posture")

                if status != self._last_detection:
                    logger.info(
                        "Camera detection flip: %s → %s (source=%s, conf=%.2f)",
                        self._last_detection, status, source, confidence,
                    )
                self._last_detection = status
                self._last_detection_at = datetime.now(timezone.utc)
                self._last_confidence = confidence
                self._last_detection_source = source
                self._last_ambient_lux = ambient_lux
                self._update_ema_lux(ambient_lux)
                # Run zone + posture hysteresis — may commit new committed values.
                self._apply_zone_hysteresis(frame_zone)
                self._apply_posture_hysteresis(frame_posture)

                # Compute the lux multiplier once — used by fusion factors,
                # the ML logger below, and the WebSocket broadcast at the end.
                current_multiplier = 1.0
                if self._calibrated and self._ema_lux is not None:
                    from backend.services.automation_engine import lux_to_multiplier
                    baseline = self._baseline_lux if self._baseline_lux is not None else 90.0
                    current_multiplier = lux_to_multiplier(
                        float(self._ema_lux), float(baseline)
                    )

                # Build factors once and reuse for both the freshness report
                # below and any edge-triggered report_activity() call, so the
                # edge call doesn't overwrite the fusion slot with an empty
                # factors list.
                camera_factors = self._build_fusion_factors(
                    status=status,
                    detection_source=source,
                    confidence=confidence,
                    multiplier=current_multiplier,
                )

                # Keep the camera lane fresh in confidence fusion every cycle.
                # The edge-triggered report_activity() calls below drive actual
                # mode changes; this keeps fusion's signal alive while the user
                # sits steadily and no transition fires.
                fusion = getattr(self._automation, "_confidence_fusion", None)
                if fusion and status in ("present", "absent"):
                    inferred = "idle" if status == "present" else "away"
                    fusion.report_signal(
                        "camera", inferred, confidence, factors=camera_factors,
                    )

                if status == "present":
                    was_absent = self._consecutive_absent >= ABSENT_THRESHOLD
                    self._consecutive_absent = 0

                    # If we were in away state, report present (idle)
                    if was_absent or self._was_absent:
                        self._was_absent = False
                        await self._automation.report_activity(
                            mode="idle", source="camera", factors=camera_factors,
                        )
                        logger.info(
                            "Presence detected via %s — reported idle "
                            "(confidence: %.2f, landmarks: %d, lux: %.0f)",
                            source or "unknown",
                            confidence,
                            pose_landmark_count,
                            ambient_lux,
                        )
                elif status == "absent":
                    self._consecutive_absent += 1

                    if self._consecutive_absent == ABSENT_THRESHOLD:
                        self._was_absent = True
                        # User has been gone long enough to call it "away" —
                        # any committed zone/posture is now stale by definition,
                        # since we have no idea where they'll re-enter from.
                        # Clearing here prevents the bed+reclined overlay from
                        # firing on values committed hours (or a sleep cycle) ago.
                        self._clear_committed_zone_posture("absent threshold")
                        await self._automation.report_activity(
                            mode="away", source="camera", factors=camera_factors,
                        )
                        logger.info(
                            "No person detected for %ds — reported away",
                            ABSENT_THRESHOLD * POLL_INTERVAL,
                        )

                # Log ML decision
                if self._ml_logger and status in ("present", "absent"):
                    mode = "away" if status == "absent" and self._consecutive_absent >= ABSENT_THRESHOLD else "idle"
                    await self._ml_logger.log_decision(
                        predicted_mode=mode,
                        confidence=confidence,
                        decision_source="camera",
                        factors={
                            "detection": status,
                            "detection_source": source,
                            "pose_landmark_count": pose_landmark_count,
                            "consecutive_absent": self._consecutive_absent,
                            "ambient_lux": ambient_lux,
                            "zone": self._last_zone,
                            "frame_zone": frame_zone,
                            "posture": self._last_posture,
                            "frame_posture": frame_posture,
                        },
                        applied=self._consecutive_absent >= ABSENT_THRESHOLD or (
                            status == "present" and self._was_absent is False
                            and was_absent if status == "present" else False
                        ),
                    )

                # Broadcast status via WebSocket (multiplier already computed above)
                await self._ws_manager.broadcast(
                    "camera_update",
                    {
                        "detection": status,
                        "detection_source": source,
                        "confidence": confidence,
                        "pose_landmark_count": pose_landmark_count,
                        "ambient_lux": ambient_lux,
                        "ema_lux": self._ema_lux,
                        "baseline_lux": self._baseline_lux,
                        "calibrated": self._calibrated,
                        "current_multiplier": current_multiplier,
                        "consecutive_absent": self._consecutive_absent,
                        "zone": self._last_zone,
                        "posture": self._last_posture,
                        "candidate_posture": self._candidate_posture,
                    },
                )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Camera poll error: %s", exc, exc_info=True)
                await asyncio.sleep(POLL_INTERVAL)

    def _clear_committed_zone_posture(self, reason: str) -> None:
        """Reset committed zone/posture (and any pending candidacy).

        Called on sustained absence and on resume from a sleeping pause —
        in both cases the prior commits are stale enough that consumers
        should treat zone/posture as unknown until a new commit lands.
        """
        if (
            self._last_zone is None
            and self._last_posture is None
            and self._candidate_zone is None
            and self._candidate_posture is None
        ):
            return
        logger.info(
            "Clearing committed zone/posture (reason=%s, was zone=%s posture=%s)",
            reason, self._last_zone, self._last_posture,
        )
        self._last_zone = None
        self._last_zone_at = None
        self._candidate_zone = None
        self._candidate_zone_since = None
        self._last_posture = None
        self._last_posture_at = None
        self._candidate_posture = None
        self._candidate_posture_since = None

    def _apply_zone_hysteresis(self, candidate: Optional[str]) -> None:
        """Update ``self._last_zone`` via a sustained-candidate rule.

        - ``candidate is None`` (no detection this frame): clear any pending
          candidacy but keep the committed zone intact — a brief absence
          must not lose the last known zone.
        - ``candidate == self._last_zone``: steady state, clear candidacy.
        - Otherwise: start or continue a candidacy timer; only commit the new
          zone after ``ZONE_HYSTERESIS_SECONDS`` of sustained detection. This
          absorbs transient detections (e.g. walking through the accent chair
          region between desk and bed) without changing the zone.
        """
        now = datetime.now(timezone.utc)

        if candidate is None:
            self._candidate_zone = None
            self._candidate_zone_since = None
            return

        if candidate == self._last_zone:
            self._candidate_zone = None
            self._candidate_zone_since = None
            return

        if candidate != self._candidate_zone:
            self._candidate_zone = candidate
            self._candidate_zone_since = now
            return

        if self._candidate_zone_since is None:
            self._candidate_zone_since = now
            return

        elapsed = (now - self._candidate_zone_since).total_seconds()
        if elapsed >= ZONE_HYSTERESIS_SECONDS:
            previous = self._last_zone or "unknown"
            logger.info(
                "Zone changed %s → %s (held %.1fs)",
                previous, candidate, elapsed,
            )
            self._last_zone = candidate
            self._last_zone_at = now
            self._candidate_zone = None
            self._candidate_zone_since = None

    def _apply_posture_hysteresis(self, candidate: Optional[str]) -> None:
        """Update ``self._last_posture`` via a sustained-candidate rule.

        Mirrors ``_apply_zone_hysteresis`` with one key difference: posture
        only fires on pose-path polls, and pose is the fallback (~1 in ~10
        polls at 2–3m corner distance — face path dominates). Treating a
        ``None`` as "reset the pending candidate" would erase progress on
        every intervening face-only poll and posture would never commit.

        So ``None`` means "signal not observed this poll" — preserve the
        pending candidate and its start time. The next non-None poll either
        reinforces the candidate (letting elapsed time commit it) or
        replaces it with a new candidate and restarts the timer.
        """
        now = datetime.now(timezone.utc)

        if candidate is None:
            return

        if candidate == self._last_posture:
            self._candidate_posture = None
            self._candidate_posture_since = None
            return

        if candidate != self._candidate_posture:
            self._candidate_posture = candidate
            self._candidate_posture_since = now
            return

        if self._candidate_posture_since is None:
            self._candidate_posture_since = now
            return

        elapsed = (now - self._candidate_posture_since).total_seconds()
        if elapsed >= POSTURE_HYSTERESIS_SECONDS:
            previous = self._last_posture or "unknown"
            logger.info(
                "Posture changed %s → %s (held %.1fs)",
                previous, candidate, elapsed,
            )
            self._last_posture = candidate
            self._last_posture_at = now
            self._candidate_posture = None
            self._candidate_posture_since = None

    def _evaluate_pose(self, pose_result: Any) -> tuple[bool, float, int]:
        """Decide whether a pose result constitutes a visible person.

        Counts torso landmarks (nose, shoulders, hips) whose visibility
        exceeds ``MIN_POSE_VISIBILITY``. Returns ``(is_present, mean_vis, count)``
        where ``mean_vis`` is the average visibility over the torso landmarks
        that passed the threshold (used as pose-path "confidence" for logging
        and fusion).
        """
        if pose_result is None or not getattr(pose_result, "pose_landmarks", None):
            return False, 0.0, 0
        landmarks = pose_result.pose_landmarks[0]
        visibilities: list[float] = []
        for idx in POSE_TORSO_INDICES:
            if idx < len(landmarks):
                vis = float(getattr(landmarks[idx], "visibility", 0.0))
                if vis >= MIN_POSE_VISIBILITY:
                    visibilities.append(vis)
        count = len(visibilities)
        if count < POSE_MIN_LANDMARKS:
            return False, 0.0, count
        mean_vis = sum(visibilities) / count
        return True, mean_vis, count

    def _evaluate_posture(self, pose_result: Any) -> Optional[str]:
        """Derive upright vs reclined from shoulder/hip Y in normalized coords.

        Returns None when hip visibility is too low to compute a meaningful
        delta — hysteresis preserves the last committed posture through brief
        pose misses rather than treating the blank as a posture change.
        """
        if pose_result is None or not getattr(pose_result, "pose_landmarks", None):
            return None
        landmarks = pose_result.pose_landmarks[0]

        def _mean_y(indices: tuple[int, ...]) -> Optional[float]:
            ys = [
                float(landmarks[i].y) for i in indices
                if i < len(landmarks)
                and float(getattr(landmarks[i], "visibility", 0.0)) >= MIN_POSE_VISIBILITY
            ]
            return sum(ys) / len(ys) if ys else None

        shoulder_y = _mean_y((POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER))
        hip_y = _mean_y((POSE_LEFT_HIP, POSE_RIGHT_HIP))
        if shoulder_y is None or hip_y is None:
            return None
        delta = hip_y - shoulder_y
        return POSTURE_UPRIGHT if delta >= POSTURE_UPRIGHT_MIN_DELTA else POSTURE_RECLINED

    def _process_frame(self) -> Optional[dict]:
        """Capture a frame, run face detection (then pose if face missed),
        compute ambient lux.

        Runs in a thread pool executor. Frames never leave this method —
        they are overwritten and dereferenced before returning.

        Returns:
            Dict with status, confidence, source, ambient_lux, and
            pose_landmark_count, or None on failure.
        """
        import cv2

        if self._cap is None or not self._cap.isOpened():
            return None

        with self._cap_lock:
            ret, frame = self._cap.read()
        if not ret or frame is None:
            return None

        try:
            import mediapipe as mp

            # Downsample if the camera returns a larger frame
            h, w = frame.shape[:2]
            if w > FRAME_WIDTH or h > FRAME_HEIGHT:
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

            # Compute ambient light level from grayscale mean
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ambient_lux = float(gray.mean())

            # Convert to RGB for MediaPipe (reused across both detectors)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            # Fast path — face detection (~15ms at 640×480)
            face_results = self._face_detector.detect(mp_image)
            if face_results.detections:
                best = max(
                    face_results.detections,
                    key=lambda d: d.categories[0].score,
                )
                # Zone from face bbox center-X (normalized by frame width).
                bbox = best.bounding_box
                cx = (bbox.origin_x + bbox.width / 2) / max(w, 1)
                zone = ZONE_DESK if cx < ZONE_DESK_THRESHOLD else ZONE_BED
                return {
                    "status": "present",
                    "confidence": float(best.categories[0].score),
                    "source": "face",
                    "pose_landmark_count": 0,
                    "ambient_lux": ambient_lux,
                    "zone": zone,
                    "posture": None,  # Face path can't derive torso geometry
                }

            # Fallback — pose landmarker (~60ms at 640×480, only on face miss)
            if self._pose_landmarker is not None:
                pose_result = self._pose_landmarker.detect(mp_image)
                is_present, mean_vis, count = self._evaluate_pose(pose_result)
                if is_present:
                    # Zone from torso midline (average of visible shoulder X).
                    zone = None
                    landmarks = pose_result.pose_landmarks[0]
                    shoulders = [
                        landmarks[idx]
                        for idx in (POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER)
                        if idx < len(landmarks)
                        and float(getattr(landmarks[idx], "visibility", 0.0))
                        >= MIN_POSE_VISIBILITY
                    ]
                    if shoulders:
                        # MediaPipe pose landmark .x is already normalized 0–1.
                        cx = sum(s.x for s in shoulders) / len(shoulders)
                        zone = ZONE_DESK if cx < ZONE_DESK_THRESHOLD else ZONE_BED
                    posture = self._evaluate_posture(pose_result)
                    return {
                        "status": "present",
                        "confidence": mean_vis,
                        "source": "pose",
                        "pose_landmark_count": count,
                        "ambient_lux": ambient_lux,
                        "zone": zone,
                        "posture": posture,
                    }

            return {
                "status": "absent",
                "confidence": 0.0,
                "source": None,
                "pose_landmark_count": 0,
                "ambient_lux": ambient_lux,
                "zone": None,
                "posture": None,
            }

        finally:
            # Privacy: ensure frame data is dereferenced
            frame = None  # noqa: F841
            rgb = None  # noqa: F841
            gray = None  # noqa: F841

    async def capture_snapshot(self, annotate: bool = False) -> Optional[bytes]:
        """Grab one frame from the existing capture device and return JPEG bytes.

        Returns None if the service is disabled, paused (sleeping mode), still
        calibrating, or the capture handle is unavailable. Frame bytes are
        never persisted to disk — only the encoded JPEG buffer is returned.
        """
        if not self._enabled or self._paused or self._calibrating:
            return None
        if self._cap is None or not self._cap.isOpened():
            return None
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._capture_snapshot_sync, annotate)

    def _capture_snapshot_sync(self, annotate: bool) -> Optional[bytes]:
        """Blocking snapshot worker. Runs in the default executor."""
        import cv2

        with self._cap_lock:
            if self._cap is None or not self._cap.isOpened():
                return None
            ret, frame = self._cap.read()

        if not ret or frame is None:
            return None

        jpeg: Optional[bytes] = None
        rgb = None
        try:
            if annotate:
                frame_h, frame_w = frame.shape[:2]
                pose_count = 0
                pose_vis = 0.0
                try:
                    import mediapipe as mp

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    # Face box
                    face_results = (
                        self._face_detector.detect(mp_image)
                        if self._face_detector else None
                    )
                    if face_results and face_results.detections:
                        for det in face_results.detections:
                            bbox = det.bounding_box
                            x1, y1 = int(bbox.origin_x), int(bbox.origin_y)
                            x2, y2 = x1 + int(bbox.width), y1 + int(bbox.height)
                            conf = float(det.categories[0].score) if det.categories else 0.0
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(
                                frame,
                                f"{conf:.2f}",
                                (x1, max(y1 - 6, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.45,
                                (0, 0, 255),
                                1,
                                cv2.LINE_AA,
                            )

                    # Pose skeleton (always draw when available for richer debug)
                    if self._pose_landmarker is not None:
                        pose_result = self._pose_landmarker.detect(mp_image)
                        _, pose_vis, pose_count = self._evaluate_pose(pose_result)
                        if pose_result and pose_result.pose_landmarks:
                            landmarks = pose_result.pose_landmarks[0]

                            def to_px(idx: int) -> Optional[tuple[int, int]]:
                                if idx >= len(landmarks):
                                    return None
                                lm = landmarks[idx]
                                if float(getattr(lm, "visibility", 0.0)) < MIN_POSE_VISIBILITY:
                                    return None
                                return (int(lm.x * frame_w), int(lm.y * frame_h))

                            # Torso edges (cyan lines)
                            for a, b in POSE_SKELETON_EDGES:
                                pa = to_px(a)
                                pb = to_px(b)
                                if pa and pb:
                                    cv2.line(frame, pa, pb, (255, 200, 0), 1, cv2.LINE_AA)

                            # Landmark dots (yellow)
                            for idx in POSE_TORSO_INDICES:
                                p = to_px(idx)
                                if p:
                                    cv2.circle(frame, p, 3, (0, 255, 255), -1, cv2.LINE_AA)
                except Exception as exc:
                    logger.warning("Snapshot annotation failed: %s", exc)

                # Zone threshold line + DESK/BED labels so framing and zone
                # classification are visible side-by-side in the overlay.
                try:
                    zone_x = int(ZONE_DESK_THRESHOLD * frame_w)
                    cv2.line(frame, (zone_x, 0), (zone_x, frame_h),
                             (180, 180, 180), 1, cv2.LINE_AA)
                    cv2.putText(frame, "DESK", (6, frame_h - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (0, 0, 0), 2, cv2.LINE_AA)
                    cv2.putText(frame, "DESK", (6, frame_h - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (220, 220, 220), 1, cv2.LINE_AA)
                    cv2.putText(frame, "BED", (zone_x + 6, frame_h - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (0, 0, 0), 2, cv2.LINE_AA)
                    cv2.putText(frame, "BED", (zone_x + 6, frame_h - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                (220, 220, 220), 1, cv2.LINE_AA)
                except Exception as exc:
                    logger.debug("Zone overlay failed: %s", exc)

                multiplier: Optional[float] = None
                if self._calibrated and self._ema_lux is not None:
                    from backend.services.automation_engine import lux_to_multiplier
                    baseline = self._baseline_lux if self._baseline_lux is not None else 90.0
                    multiplier = lux_to_multiplier(float(self._ema_lux), float(baseline))

                zone_display = self._last_zone or "--"
                if self._candidate_zone and self._candidate_zone != self._last_zone:
                    zone_display += f" (→{self._candidate_zone})"

                overlay_lines = [
                    f"ema_lux={self._ema_lux:.1f}" if self._ema_lux is not None else "ema_lux=--",
                    f"baseline={self._baseline_lux:.1f}" if self._baseline_lux is not None else "baseline=--",
                    f"mult={multiplier:.2f}" if multiplier is not None else "mult=--",
                    f"detection={self._last_detection}",
                    f"src={self._last_detection_source or '--'}",
                    f"pose_vis={pose_vis:.2f} ({pose_count}/{len(POSE_TORSO_INDICES)})" if pose_count else "pose_vis=--",
                    f"zone={zone_display}",
                ]
                for i, line in enumerate(overlay_lines):
                    y = 14 + i * 14
                    cv2.putText(frame, line, (5, y), cv2.FONT_HERSHEY_SIMPLEX,
                                0.4, (0, 0, 0), 2, cv2.LINE_AA)
                    cv2.putText(frame, line, (5, y), cv2.FONT_HERSHEY_SIMPLEX,
                                0.4, (255, 255, 255), 1, cv2.LINE_AA)

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return None
            jpeg = buf.tobytes()
        finally:
            # Privacy: drop frame references before returning.
            frame = None  # noqa: F841
            rgb = None  # noqa: F841

        return jpeg

    async def on_mode_change(self, new_mode: str) -> None:
        """Mode-change callback — pause polling during sleeping mode.

        Pausing turns off the camera (LED goes dark) for sleep privacy.
        """
        if new_mode == "sleeping":
            if not self._paused:
                self._paused = True
                if self._heartbeat is not None:
                    self._heartbeat.deregister("camera")
                # Release camera so LED turns off
                if self._cap and self._cap.isOpened():
                    self._cap.release()
                logger.info("Camera paused for sleeping mode")
        else:
            if self._paused:
                self._paused = False
                if self._heartbeat is not None:
                    self._heartbeat.register("camera", float(POLL_INTERVAL))
                # The pause spanned at least the sleep cycle — any committed
                # zone/posture from before sleep is stale and would otherwise
                # leak into the morning's first overlay decisions.
                self._clear_committed_zone_posture("resume from sleeping")
                # Reopen camera
                try:
                    import cv2
                    self._cap = cv2.VideoCapture(0)
                    if self._cap.isOpened():
                        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                        logger.info("Camera resumed after sleeping mode")
                    else:
                        logger.warning("Camera unavailable after sleep — will retry next poll")
                        self._cap = None
                except Exception as exc:
                    logger.error("Failed to reopen camera: %s", exc)
                    self._cap = None

    async def close(self) -> None:
        """Release camera and MediaPipe resources."""
        self._enabled = False
        if self._heartbeat is not None:
            self._heartbeat.deregister("camera")
        if self._cap and self._cap.isOpened():
            self._cap.release()
            self._cap = None
        if self._face_detector:
            self._face_detector.close()
            self._face_detector = None
        if self._pose_landmarker:
            self._pose_landmarker.close()
            self._pose_landmarker = None
        logger.info("Camera service stopped")

    def get_status(self) -> dict:
        """Return current camera service status for health checks."""
        return {
            "enabled": self._enabled,
            "paused": self._paused,
            "last_detection": self._last_detection,
            "detection_source": self._last_detection_source,
            "confidence": self._last_confidence,
            "pose_available": self._pose_landmarker is not None,
            "ambient_lux": self._last_ambient_lux,
            "ema_lux": self._ema_lux,
            "baseline_lux": self._baseline_lux,
            "calibrated": self._calibrated,
            "calibrating": self._calibrating,
            "exposure_value": self._exposure_value,
            "consecutive_absent": self._consecutive_absent,
            "poll_interval": POLL_INTERVAL,
            "absent_threshold": ABSENT_THRESHOLD,
            "zone": self._last_zone,
            "candidate_zone": self._candidate_zone,
            "posture": self._last_posture,
            "candidate_posture": self._candidate_posture,
        }
