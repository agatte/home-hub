"""Camera presence detection — MediaPipe face detection on the Latitude webcam.

Captures one frame every 5 seconds from the built-in webcam, runs MediaPipe
Face Detection to determine room occupancy, and reports presence/absence to the
automation engine. Also measures ambient light level from frame luminance.

Phase 2a: Presence only (face detection, ~5ms per frame).
Phase 2b (future): Posture classification via BlazePose (upright vs reclined).

Privacy guarantees:
  - Frames are numpy arrays in memory only, overwritten each cycle.
  - Frames never touch disk, network, logs, or any API response.
  - Only derived labels (present/absent), confidence, and lux values persist.
  - Opt-in via camera_enabled app setting (default false).
  - Dell Latitude camera LED activates when capturing (hardware-enforced).
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("home_hub.camera")

# Polling and detection constants
POLL_INTERVAL = 5       # Seconds between frame captures
FRAME_WIDTH = 320       # Downsampled frame size for inference
FRAME_HEIGHT = 240
ABSENT_THRESHOLD = 3    # Consecutive absent frames before reporting away (15s)
MIN_FACE_CONFIDENCE = 0.5

# Ambient lux calibration constants. Auto-exposure is disabled when a
# calibration is present so gray.mean() reflects actual room brightness
# instead of the webcam compensating with its aperture.
EXPOSURE_TARGET_LUX = 100   # Target frame mean at calibration time
EXPOSURE_TOLERANCE = 10     # Accept calibration within target ± tolerance
CALIBRATION_FRAMES = 10     # Frames averaged per exposure probe
LUX_EMA_ALPHA = 0.1         # Smoothing factor (α*raw + (1-α)*ema)
LUX_CALIBRATION_SETTING_KEY = "lux_calibration_config"
# OpenCV DirectShow/V4L2 auto-exposure magic numbers:
#   0.25 = manual exposure, 0.75 = auto (on Windows DShow backend)
CAP_AUTO_EXPOSURE_MANUAL = 0.25

# Model file for MediaPipe Tasks API (v0.10.20+)
MODEL_DIR = Path("data/models")
MODEL_FILENAME = "blaze_face_short_range.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_detector/blaze_face_short_range/float16/latest/"
    "blaze_face_short_range.tflite"
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
        self._face_detector = None

        # Detection state
        self._consecutive_absent: int = 0
        self._last_detection: str = "unknown"
        self._last_confidence: float = 0.0
        self._last_ambient_lux: float = 0.0
        self._was_absent: bool = False

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
        """Open the webcam and initialize MediaPipe face detection.

        Fails gracefully if the camera is unavailable (busy, missing, etc.).
        Downloads the face detection model on first run (~230KB).
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
        model_path = MODEL_DIR / MODEL_FILENAME
        if not model_path.exists():
            if not self._download_model(model_path):
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
                base_options=BaseOptions(model_asset_path=str(model_path)),
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

        self._enabled = True
        logger.info("Camera presence detection started (polling every %ds)", POLL_INTERVAL)

    @staticmethod
    def _download_model(model_path: Path) -> bool:
        """Download the BlazeFace short-range model from Google.

        Returns:
            True if download succeeded.
        """
        try:
            import httpx

            model_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Downloading face detection model...")
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(MODEL_URL)
                resp.raise_for_status()
                model_path.write_bytes(resp.content)
            logger.info(
                "Face detection model saved (%d bytes)", len(resp.content)
            )
            return True
        except Exception as exc:
            logger.error("Failed to download face detection model: %s", exc)
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
        """Blocking calibration search. Runs in executor."""
        import cv2

        # Switch to manual exposure so our writes take effect.
        self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, CAP_AUTO_EXPOSURE_MANUAL)

        # DShow range varies by driver (Latitude webcam clamps around -13).
        # Start wide so we avoid bottoming out the search unnecessarily — if
        # the driver clamps further, measure() still returns the clamped-value
        # reading and the search converges on whatever the camera can deliver.
        lo, hi = -20.0, 5.0

        def measure(exposure: float) -> float:
            self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            # Let the sensor settle — drop 3 frames, average the rest
            for _ in range(3):
                self._cap.read()
            readings = []
            for _ in range(CALIBRATION_FRAMES):
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                readings.append(float(gray.mean()))
            if not readings:
                return -1.0
            return sum(readings) / len(readings)

        # Widen the bracket if target is outside [measure(lo), measure(hi)]
        lo_lux = measure(lo)
        hi_lux = measure(hi)
        if lo_lux < 0 or hi_lux < 0:
            return {"status": "error", "detail": "camera read failed during calibration"}

        # Ensure the target is inside the bracket (grow outward up to 2 tries)
        tries = 0
        while hi_lux < EXPOSURE_TARGET_LUX - EXPOSURE_TOLERANCE and tries < 2:
            hi += 2.0
            hi_lux = measure(hi)
            tries += 1
        tries = 0
        while lo_lux > EXPOSURE_TARGET_LUX + EXPOSURE_TOLERANCE and tries < 2:
            lo -= 2.0
            lo_lux = measure(lo)
            tries += 1

        # Binary search
        best_exposure = (lo + hi) / 2
        best_lux = 0.0
        for _ in range(8):  # 8 iterations → ~0.04 exposure resolution
            mid = (lo + hi) / 2
            mid_lux = measure(mid)
            if mid_lux < 0:
                return {"status": "error", "detail": "camera read failed mid-search"}
            best_exposure, best_lux = mid, mid_lux
            if abs(mid_lux - EXPOSURE_TARGET_LUX) <= EXPOSURE_TOLERANCE:
                break
            if mid_lux < EXPOSURE_TARGET_LUX:
                lo = mid  # Need brighter → increase exposure
            else:
                hi = mid  # Too bright → decrease exposure

        return {
            "status": "ok",
            "exposure_value": best_exposure,
            "measured_lux": best_lux,
            "detail": (
                f"calibrated: exposure={best_exposure:.2f}, "
                f"measured_lux={best_lux:.1f}"
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

    async def poll_loop(self) -> None:
        """Background task — capture and classify one frame every POLL_INTERVAL seconds."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)

                if not self._enabled or self._paused:
                    continue

                # Run blocking frame capture + inference in thread pool
                result = await loop.run_in_executor(None, self._process_frame)
                if result is None:
                    continue

                status = result["status"]
                confidence = result["confidence"]
                ambient_lux = result["ambient_lux"]

                self._last_detection = status
                self._last_confidence = confidence
                self._last_ambient_lux = ambient_lux
                self._update_ema_lux(ambient_lux)

                # Keep the camera lane fresh in confidence fusion every cycle.
                # The edge-triggered report_activity() calls below drive actual
                # mode changes; this keeps fusion's signal alive while the user
                # sits steadily and no transition fires.
                fusion = getattr(self._automation, "_confidence_fusion", None)
                if fusion and status in ("present", "absent"):
                    inferred = "idle" if status == "present" else "away"
                    fusion.report_signal("camera", inferred, confidence)

                if status == "present":
                    was_absent = self._consecutive_absent >= ABSENT_THRESHOLD
                    self._consecutive_absent = 0

                    # If we were in away state, report present (idle)
                    if was_absent or self._was_absent:
                        self._was_absent = False
                        await self._automation.report_activity(
                            mode="idle", source="camera"
                        )
                        logger.info(
                            "Presence detected — reported idle "
                            "(confidence: %.2f, lux: %.0f)",
                            confidence,
                            ambient_lux,
                        )
                elif status == "absent":
                    self._consecutive_absent += 1

                    if self._consecutive_absent == ABSENT_THRESHOLD:
                        self._was_absent = True
                        await self._automation.report_activity(
                            mode="away", source="camera"
                        )
                        logger.info(
                            "No face detected for %ds — reported away",
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
                            "consecutive_absent": self._consecutive_absent,
                            "ambient_lux": ambient_lux,
                        },
                        applied=self._consecutive_absent >= ABSENT_THRESHOLD or (
                            status == "present" and self._was_absent is False
                            and was_absent if status == "present" else False
                        ),
                    )

                # Broadcast status via WebSocket
                current_multiplier = 1.0
                if self._calibrated and self._ema_lux is not None:
                    from backend.services.automation_engine import lux_to_multiplier
                    baseline = self._baseline_lux if self._baseline_lux is not None else 90.0
                    current_multiplier = lux_to_multiplier(
                        float(self._ema_lux), float(baseline)
                    )
                await self._ws_manager.broadcast(
                    "camera_update",
                    {
                        "detection": status,
                        "confidence": confidence,
                        "ambient_lux": ambient_lux,
                        "ema_lux": self._ema_lux,
                        "baseline_lux": self._baseline_lux,
                        "calibrated": self._calibrated,
                        "current_multiplier": current_multiplier,
                        "consecutive_absent": self._consecutive_absent,
                    },
                )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Camera poll error: %s", exc, exc_info=True)
                await asyncio.sleep(POLL_INTERVAL)

    def _process_frame(self) -> Optional[dict]:
        """Capture a frame, run face detection, compute ambient lux.

        Runs in a thread pool executor. Frames never leave this method —
        they are overwritten and dereferenced before returning.

        Returns:
            Dict with status, confidence, and ambient_lux, or None on failure.
        """
        import cv2

        if self._cap is None or not self._cap.isOpened():
            return None

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

            # Convert to RGB for MediaPipe
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Wrap in MediaPipe Image for Tasks API
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            # Run face detection
            results = self._face_detector.detect(mp_image)

            # Determine presence
            if results.detections:
                # Take highest confidence detection
                best = max(
                    results.detections,
                    key=lambda d: d.categories[0].score,
                )
                status = "present"
                confidence = float(best.categories[0].score)
            else:
                status = "absent"
                confidence = 0.0

            return {
                "status": status,
                "confidence": confidence,
                "ambient_lux": ambient_lux,
            }

        finally:
            # Privacy: ensure frame data is dereferenced
            frame = None  # noqa: F841
            rgb = None  # noqa: F841
            gray = None  # noqa: F841

    async def on_mode_change(self, new_mode: str) -> None:
        """Mode-change callback — pause polling during sleeping mode.

        Pausing turns off the camera (LED goes dark) for sleep privacy.
        """
        if new_mode == "sleeping":
            if not self._paused:
                self._paused = True
                # Release camera so LED turns off
                if self._cap and self._cap.isOpened():
                    self._cap.release()
                logger.info("Camera paused for sleeping mode")
        else:
            if self._paused:
                self._paused = False
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
        if self._cap and self._cap.isOpened():
            self._cap.release()
            self._cap = None
        if self._face_detector:
            self._face_detector.close()
            self._face_detector = None
        logger.info("Camera service stopped")

    def get_status(self) -> dict:
        """Return current camera service status for health checks."""
        return {
            "enabled": self._enabled,
            "paused": self._paused,
            "last_detection": self._last_detection,
            "confidence": self._last_confidence,
            "ambient_lux": self._last_ambient_lux,
            "ema_lux": self._ema_lux,
            "baseline_lux": self._baseline_lux,
            "calibrated": self._calibrated,
            "calibrating": self._calibrating,
            "exposure_value": self._exposure_value,
            "consecutive_absent": self._consecutive_absent,
            "poll_interval": POLL_INTERVAL,
            "absent_threshold": ABSENT_THRESHOLD,
        }
