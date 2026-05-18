"""
Emotion Capture — desktop pc_agent that POSTs FaceLandmarker blendshapes.

Counterpart to the Latitude's camera_service blendshape pass. The desktop
webcam is frontal most of the working day, so the 52 ARKit blendshapes
land well-formed (no foreshortening); the Latitude path covers off-hours
and the bed scenario where the desktop is asleep. Backend EmotionService
prefers desktop within a 30s freshness window, otherwise falls back.

Privacy contract (mirrors camera_service.py):
    - Raw frames are numpy arrays in memory only, dereferenced each cycle.
    - Frames never touch disk, network, logs, or any API response.
    - Only the derived 52-float blendshape dict + face confidence cross
      the LAN to /api/personality/blendshape.
    - Opt-in via desktop_emotion_enabled app_setting (default false). The
      agent polls the setting every 30s so the toggle takes effect without
      a supervisor restart.
    - Webcam LED activates when capturing (hardware-enforced).

Usage (normally launched by supervisor.py, not directly):
    python -m backend.services.pc_agent.emotion_capture --server http://192.168.1.210:8000
"""
import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import httpx

# Cadences. 2s capture stride matches the EmotionService EMA's expected
# input rate; 30s settings-poll keeps the enable flag responsive without
# hammering the backend.
CAPTURE_INTERVAL = 2.0
SETTINGS_POLL_INTERVAL = 30.0

# Minimum face confidence below which we don't POST. Mirrors the
# FACE_LANDMARKER_TRIGGER_CONFIDENCE constant in camera_service.py so the
# two sources gate on the same floor.
FACE_CONFIDENCE_FLOOR = 0.30

# FaceLandmarker model — fetched on first run into local data/models/.
# Same URL the Latitude uses; each host downloads its own ~3MB copy.
MODEL_DIR = Path("data/models")
FACE_LANDMARKER_MODEL_FILENAME = "face_landmarker.task"
FACE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/"
    "face_landmarker.task"
)

HTTP_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# Logging — file + console (file captures errors even under pythonw.exe)
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "emotion_capture.log"

logger = logging.getLogger("home_hub.emotion_capture")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)


# ---------------------------------------------------------------------------
# FaceLandmarker bootstrap
# ---------------------------------------------------------------------------


def _download_model(model_path: Path, url: str) -> bool:
    """Fetch the FaceLandmarker .task file. Returns False on failure."""
    try:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading FaceLandmarker model from %s ...", url)
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            model_path.write_bytes(resp.content)
        logger.info("FaceLandmarker model saved (%d bytes)", len(resp.content))
        return True
    except Exception as exc:
        logger.error("Failed to download FaceLandmarker model: %s", exc)
        return False


def _init_face_landmarker() -> Optional[Any]:
    """Lazy-create a FaceLandmarker instance. Returns None on failure."""
    try:
        import mediapipe as mp
    except ImportError:
        logger.warning(
            "mediapipe not installed on this host — emotion_capture disabled"
        )
        return None

    model_path = MODEL_DIR / FACE_LANDMARKER_MODEL_FILENAME
    if not model_path.exists():
        if not _download_model(model_path, FACE_LANDMARKER_MODEL_URL):
            return None

    try:
        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        landmarker = FaceLandmarker.create_from_options(options)
        logger.info("FaceLandmarker initialized")
        return landmarker
    except Exception as exc:
        logger.warning("FaceLandmarker init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Capture worker
# ---------------------------------------------------------------------------


class EmotionCapture:
    """Per-frame webcam → blendshape → POST pipeline."""

    def __init__(self, server_url: str) -> None:
        self._server_url = server_url.rstrip("/")
        self._blendshape_endpoint = f"{self._server_url}/api/personality/blendshape"
        self._settings_endpoint = f"{self._server_url}/api/personality/settings"

        # Runtime toggle, refreshed by the settings-poll thread. Defaults
        # to False so we don't capture before the user has opted in via
        # the /personality page — the supervisor restart that picks up this
        # agent is the same operation that lets the user flip the toggle.
        self._enabled: bool = False
        self._enabled_lock = threading.Lock()

        # Lazy-init handles
        self._cap = None
        self._landmarker = None
        self._mp_image_cls = None  # cached mp.Image constructor

        # Webcam-unavailable transition tracking. Mirrors the LoL
        # _note_lol_failure pattern in activity_detector.py — log a
        # single WARN on transition rather than flooding the log when
        # Zoom / Discord holds the device.
        self._last_unavailable_reason: Optional[str] = None

        self._client = httpx.Client(timeout=HTTP_TIMEOUT_S)

    # ── lifecycle ───────────────────────────────────────────────────

    def close(self) -> None:
        """Release the webcam handle + HTTP client. Idempotent."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                pass
            self._landmarker = None
        try:
            self._client.close()
        except Exception:
            pass

    # ── enable flag ─────────────────────────────────────────────────

    def set_enabled(self, value: bool) -> None:
        with self._enabled_lock:
            if self._enabled != value:
                logger.info("desktop_emotion_enabled → %s", value)
            self._enabled = value

    def is_enabled(self) -> bool:
        with self._enabled_lock:
            return self._enabled

    # ── webcam ──────────────────────────────────────────────────────

    def _ensure_cap(self) -> bool:
        """Open cv2.VideoCapture(0) if not already. Returns True on success."""
        if self._cap is not None:
            return True
        try:
            import cv2  # type: ignore
        except ImportError:
            self._note_webcam_unavailable("opencv_not_installed")
            return False
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self._note_webcam_unavailable("open_failed")
                cap.release()
                return False
            self._cap = cap
            logger.info("Webcam opened (cv2.VideoCapture(0))")
            self._last_unavailable_reason = None
            return True
        except Exception as exc:
            self._note_webcam_unavailable(f"open_exception:{type(exc).__name__}")
            return False

    def _release_cap(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _note_webcam_unavailable(self, reason: str) -> None:
        """Log a single WARN per failure-mode transition."""
        if reason == self._last_unavailable_reason:
            return
        logger.warning("Webcam unavailable: %s", reason)
        self._last_unavailable_reason = reason

    # ── one capture+detect+post cycle ───────────────────────────────

    def tick(self) -> None:
        """Run one capture cycle. Silent on the happy path; logs only anomalies."""
        if not self.is_enabled():
            # Release the webcam so other apps (Zoom, Discord) can grab it
            # while we're disabled. Inexpensive — cv2 reopens on next enable.
            self._release_cap()
            return

        # Lazy-init landmarker on first enabled tick. On transient failure
        # (download error, init race, mediapipe missing), the next tick
        # retries automatically since ``_landmarker`` stays None.
        if self._landmarker is None:
            self._landmarker = _init_face_landmarker()
            if self._landmarker is None:
                return
            try:
                import mediapipe as mp  # type: ignore
                self._mp_image_cls = mp.Image
                self._mp_image_format = mp.ImageFormat.SRGB
            except ImportError:
                self._landmarker = None
                return

        if not self._ensure_cap():
            return

        try:
            import cv2  # type: ignore
        except ImportError:
            self._note_webcam_unavailable("opencv_not_installed")
            return

        frame = None
        rgb = None
        try:
            ret, frame = self._cap.read() if self._cap is not None else (False, None)
            if not ret or frame is None:
                self._note_webcam_unavailable("read_returned_false")
                # Drop the handle so the next tick reopens — handles the
                # exclusive-lock release case after Zoom/Discord closes.
                self._release_cap()
                return

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = self._mp_image_cls(
                image_format=self._mp_image_format, data=rgb
            )

            try:
                result = self._landmarker.detect(mp_image)
            except Exception:
                logger.debug("FaceLandmarker.detect failed", exc_info=True)
                return

            face_blendshapes = getattr(result, "face_blendshapes", None) or []
            if not face_blendshapes:
                return

            shapes = face_blendshapes[0]
            blendshape_dict = {
                cat.category_name: float(cat.score) for cat in shapes
            }

            # FaceLandmarker doesn't expose a top-level face confidence in
            # the same way BlazeFace does. Use the maximum non-neutral
            # category score as a coarse proxy — when nothing's in front
            # of the camera, all categories collapse to ~0 and the gate
            # filters us out. When a face is present, several categories
            # land in the 0.3–0.9 range.
            face_confidence = max(
                (
                    score
                    for name, score in blendshape_dict.items()
                    if name != "_neutral"
                ),
                default=0.0,
            )

            if face_confidence < FACE_CONFIDENCE_FLOOR:
                return

            self._post_blendshapes(blendshape_dict, face_confidence)
        finally:
            # Explicit dereference so the numpy buffers go out of scope
            # before the next tick — mirrors camera_service's finally pattern.
            frame = None
            rgb = None

    def _post_blendshapes(
        self, blendshapes: dict[str, float], face_confidence: float
    ) -> None:
        payload = {
            "blendshapes": blendshapes,
            "face_confidence": face_confidence,
            "source": "desktop",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = self._client.post(self._blendshape_endpoint, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "POST /blendshape returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.debug("POST /blendshape failed: %s", exc)

    # ── settings poll ───────────────────────────────────────────────

    def poll_settings(self) -> None:
        """Refresh the enabled flag from /api/personality/settings.

        On transient errors (network blip, backend restart) we leave the
        current flag alone — better than going silent during a deploy.
        """
        try:
            resp = self._client.get(self._settings_endpoint)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.debug("Settings poll failed: %s", exc)
            return
        except ValueError:
            logger.debug("Settings poll returned non-JSON")
            return

        personality = bool(data.get("personality_enabled"))
        desktop = bool(data.get("desktop_emotion_enabled"))
        self.set_enabled(personality and desktop)


# ---------------------------------------------------------------------------
# Threaded supervisor entry point
# ---------------------------------------------------------------------------


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Supervisor entry point. Runs capture + settings polling until stopped.

    Mirrors the signature of activity_detector.run_agent so the
    supervisor's AgentState dispatcher can drop this in without special
    casing. The capture and settings loops share the same stop_event,
    so a single supervisor stop tears down both.
    """
    _stop = stop_event or threading.Event()
    capture = EmotionCapture(server_url)

    logger.info(
        "Emotion capture started — POSTing to %s/api/personality/blendshape",
        server_url.rstrip("/"),
    )

    # Seed the enabled flag immediately so we don't sit at default-off
    # for the full 30s poll interval after a fresh supervisor start.
    capture.poll_settings()

    def _settings_loop() -> None:
        while not _stop.is_set():
            if _stop.wait(SETTINGS_POLL_INTERVAL):
                return
            capture.poll_settings()

    settings_thread = threading.Thread(
        target=_settings_loop, name="emotion_capture-settings", daemon=True,
    )
    settings_thread.start()

    try:
        while not _stop.is_set():
            try:
                capture.tick()
            except Exception:
                logger.error("emotion_capture tick failed", exc_info=True)
            _stop.wait(CAPTURE_INTERVAL)
    finally:
        capture.close()
        settings_thread.join(timeout=2.0)
        logger.info("Emotion capture stopped")


# ---------------------------------------------------------------------------
# CLI entry point (manual testing — supervisor is the normal launcher)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Home Hub desktop emotion capture (FaceLandmarker → blendshape POST)",
    )
    parser.add_argument(
        "--server",
        default="http://192.168.1.210:8000",
        help="Home Hub server URL (default: http://192.168.1.210:8000)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    run_agent(args.server)
