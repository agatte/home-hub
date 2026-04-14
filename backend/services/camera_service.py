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
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("home_hub.camera")

# Polling and detection constants
POLL_INTERVAL = 5       # Seconds between frame captures
FRAME_WIDTH = 320       # Downsampled frame size for inference
FRAME_HEIGHT = 240
ABSENT_THRESHOLD = 3    # Consecutive absent frames before reporting away (15s)
MIN_FACE_CONFIDENCE = 0.5

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
                await self._ws_manager.broadcast(
                    "camera_update",
                    {
                        "detection": status,
                        "confidence": confidence,
                        "ambient_lux": ambient_lux,
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
            "consecutive_absent": self._consecutive_absent,
            "poll_interval": POLL_INTERVAL,
            "absent_threshold": ABSENT_THRESHOLD,
        }
