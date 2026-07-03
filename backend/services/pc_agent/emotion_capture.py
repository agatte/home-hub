"""
Emotion Capture + Desktop Presence — desktop pc_agent that POSTs
FaceLandmarker blendshapes (mood) AND tagged presence observations.

Counterpart to the Latitude's camera_service. Each tick runs MediaPipe
FaceLandmarker once; depending on which toggles are enabled the agent:
  - POSTs blendshapes to /api/personality/blendshape (emotion gate)
  - POSTs a PresenceReading to /api/camera/observation (presence gate)

The two toggles are independent because the privacy implications differ
(emotion infers mood from your face; presence just says "the desk is
occupied"). Either, neither, or both can be on.

Privacy contract (mirrors camera_service.py):
    - Raw frames are numpy arrays in memory only, dereferenced each cycle.
    - Frames never touch disk, network, logs, or any API response.
    - Only derived values cross the LAN: 52-float blendshape dict +
      face confidence (emotion path); face_present bool + face_confidence
      + timestamp (presence path).
    - Opt-in via desktop_emotion_enabled / desktop_presence_enabled
      app_settings (both default false). The agent polls them every 30s
      so toggles take effect without a supervisor restart.
    - Webcam LED activates when capturing (hardware-enforced).

Usage (normally launched by supervisor.py, not directly):
    python -m backend.services.pc_agent.emotion_capture --server http://192.168.86.210:8000
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
from typing import Any, Callable, Optional

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

# PoseLandmarker (lite ~5MB) — same model + URL the Latitude uses, each
# host downloads its own copy. Required for frontal-posture (upright vs
# slouched) classification. Lite variant emits 2D normalized landmarks +
# visibility — the world (3D) variant isn't needed for the head-drop ratio.
POSE_LANDMARKER_MODEL_FILENAME = "pose_landmarker_lite.task"
POSE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)

# BlazePose landmark indices (canonical, see MediaPipe pose_landmarker docs).
POSE_NOSE = 0
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12
POSE_LEFT_HIP = 23
POSE_RIGHT_HIP = 24

# Posture classification — normalized head-drop ratio between shoulder
# midpoint and hip midpoint. Distance-invariant because torso height
# normalizes how close the user sits. Dead-band 0.46..0.54 protects
# against single-frame jitter near the boundary; classifier keeps the
# prior commit when the reading falls in the dead-band.
POSTURE_UPRIGHT = "upright"
POSTURE_SLOUCHED = "slouched"
POSTURE_UPRIGHT_MAX = 0.46  # ratio ≤ this → upright
POSTURE_SLOUCHED_MIN = 0.54  # ratio ≥ this → slouched
POSTURE_THRESHOLD_CENTER = 0.50  # for confidence calc
# Visibility floor for the five landmarks the classifier needs. Loosened
# from the Latitude's 0.8 because the desktop's frontal close-range view
# is high-confidence; 0.6 keeps real readings + rejects extrapolated ones.
POSE_MIN_VISIBILITY = 0.6
# Frame-streak hysteresis — candidate must hold for this many consecutive
# ticks before transitioning. At the 2s capture cadence this is ~6s,
# tight enough that real slouching-onset is caught in <10s and noisy
# enough single ticks don't flip the merged signal.
POSTURE_HYSTERESIS_FRAMES = 3

# Fallback classifier — used when the hip-based head-drop ratio can't be
# computed (hips occluded by desk / below frame). Computes a shoulder-
# anchored ratio: how far above the shoulder line the nose sits,
# normalized by shoulder width. Distance-invariant because shoulder width
# scales with user-camera distance the same way nose-to-shoulder Y does.
#
# Sign flipped vs head_drop: HIGH ratio = head well above shoulders =
# upright; LOW ratio = head dropped toward shoulder line = slouched.
#
# Calibrated 2026-05-18 against Anthony's desk geometry. A 25-frame
# diag pass over ~13 minutes showed natural posture clustering at
# ratio 0.30–0.47 (median 0.385), with a single deliberate-upright
# moment hitting 0.55. The wide dead-band [0.30, 0.50] means the
# natural posture sits in "no commit" territory — the classifier only
# fires upright when Anthony sits up tall and only fires slouched when
# he visibly slumps. Outliers (pose detector single-frame glitches
# producing ratios < 0.05) get muted by the 3-frame streak hysteresis.
HEAD_ABOVE_SHOULDER_UPRIGHT_MIN = 0.50  # ratio ≥ this → upright
HEAD_ABOVE_SHOULDER_SLOUCHED_MAX = 0.30  # ratio ≤ this → slouched
HEAD_ABOVE_SHOULDER_THRESHOLD_CENTER = 0.40  # for confidence calc

HTTP_TIMEOUT_S = 5.0

# Bedroom-lux calibration + sampling (D4). DirectShow exposure conventions
# mirror CameraService: 0.75 = auto, 0.25 = manual.
EXPOSURE_AUTO = 0.75
EXPOSURE_MANUAL = 0.25
LUX_CALIBRATION_TARGET = 100.0   # gray.mean() we aim for at comfortable-bright
# Acceptable steady-state mean band to stop the search in (mirrors
# camera_service._calibrate_exposure_sync). Outside [60,180] the room is
# too dark / too bright to anchor a useful baseline.
LUX_ACCEPT_LO = 60.0
LUX_ACCEPT_HI = 180.0
LUX_EXPOSURE_MIN = -12.0
LUX_EXPOSURE_MAX = 0.0

# Part A periodic sampling. ~25s keeps the backend bedroom_lux channel under
# its 30s staleness gate while bounding how often the brief flip-to-fixed-
# exposure interrupts face capture. A sample skips ONE presence tick.
LUX_SAMPLE_INTERVAL_S = 25.0
LUX_SAMPLE_SETTLE_S = 0.4   # AGC settle after switching to the fixed exposure
LUX_SAMPLE_FRAMES = 3       # frames averaged for one lux reading


# ---------------------------------------------------------------------------
# Pure classifier helpers (testable without MediaPipe installed)
# ---------------------------------------------------------------------------


def search_exposure(
    measure_fn,
    *,
    start: float = -6.0,
    lo: float = LUX_ACCEPT_LO,
    hi: float = LUX_ACCEPT_HI,
    exp_min: float = LUX_EXPOSURE_MIN,
    exp_max: float = LUX_EXPOSURE_MAX,
    max_iter: int = 6,
) -> tuple[float, float]:
    """Find a fixed exposure whose steady ``gray.mean()`` lands in ``[lo, hi]``.

    Pure + camera-agnostic: ``measure_fn(exposure) -> float`` returns the
    steady-state mean at that exposure (or a negative value on read failure).
    Starts at ``start`` and steps ±2 stops (each ≈ halve/double brightness)
    toward the band, clamped to ``[exp_min, exp_max]``. Returns
    ``(exposure, measured)`` — the last exposure tried and its mean. A
    negative ``measured`` signals a read failure; a measured outside
    ``[lo, hi]`` means the search exhausted ``max_iter`` without landing
    (room too dark/bright — caller should warn). Mirrors the binary-ish
    sweep in ``camera_service._calibrate_exposure_sync`` but full-frame.
    """
    exposure = start
    measured = -1.0
    for _ in range(max_iter):
        measured = measure_fn(exposure)
        if measured < 0:
            return exposure, measured  # read failure — abort
        if lo <= measured <= hi:
            break
        exposure += -2.0 if measured > hi else 2.0
        exposure = max(exp_min, min(exp_max, exposure))
    return exposure, measured


def _compute_head_drop_ratio(
    pose_landmarks: Any,
    min_visibility: float = POSE_MIN_VISIBILITY,
) -> Optional[float]:
    """Return ``(shoulder_mid.y - nose.y) / (hip_mid.y - nose.y)``.

    Returns ``None`` when any of the five required landmarks (nose, both
    shoulders, both hips) has visibility below ``min_visibility``, or
    when the torso height collapses to ~0 (degenerate geometry from a
    misdetection). The ratio is distance-invariant because the
    denominator absorbs camera-distance scaling.

    ``pose_landmarks`` is the MediaPipe Tasks API ``pose_landmarks[0]``
    list — each element exposes ``.x``, ``.y``, ``.visibility`` in 0..1
    normalized image coordinates (Y=0 top, Y=1 bottom).
    """
    if pose_landmarks is None:
        return None
    try:
        nose = pose_landmarks[POSE_NOSE]
        ls = pose_landmarks[POSE_LEFT_SHOULDER]
        rs = pose_landmarks[POSE_RIGHT_SHOULDER]
        lh = pose_landmarks[POSE_LEFT_HIP]
        rh = pose_landmarks[POSE_RIGHT_HIP]
    except (IndexError, TypeError):
        return None

    for lm in (nose, ls, rs, lh, rh):
        if getattr(lm, "visibility", 0.0) < min_visibility:
            return None

    shoulder_mid_y = (ls.y + rs.y) / 2.0
    hip_mid_y = (lh.y + rh.y) / 2.0
    torso_height = hip_mid_y - nose.y
    # Degenerate geometry: hip above (or at) nose. Real anatomy can't
    # produce this; if the lite model emits it, the frame is unusable.
    if torso_height <= 1e-3:
        return None

    return (shoulder_mid_y - nose.y) / torso_height


def _classify_posture(
    head_drop: Optional[float],
    prior: Optional[str],
) -> tuple[Optional[str], Optional[float]]:
    """Map head-drop ratio to ``(posture, confidence)`` with a dead-band.

    - ``head_drop <= POSTURE_UPRIGHT_MAX`` → ``"upright"``
    - ``head_drop >= POSTURE_SLOUCHED_MIN`` → ``"slouched"``
    - Between the two → keep ``prior`` (dead-band against flicker)
    - ``head_drop is None`` → ``(None, None)``

    Confidence is ``min(1.0, abs(head_drop - 0.50) * 5.0)`` — low near
    the boundary, saturates to 1.0 for unambiguous readings.
    """
    if head_drop is None:
        return None, None
    confidence = min(1.0, abs(head_drop - POSTURE_THRESHOLD_CENTER) * 5.0)
    if head_drop <= POSTURE_UPRIGHT_MAX:
        return POSTURE_UPRIGHT, confidence
    if head_drop >= POSTURE_SLOUCHED_MIN:
        return POSTURE_SLOUCHED, confidence
    # Dead-band — preserve prior commit if any, else stay None.
    return prior, confidence if prior is not None else None


def _compute_head_above_shoulders_ratio(
    pose_landmarks: Any,
    min_visibility: float = POSE_MIN_VISIBILITY,
) -> Optional[float]:
    """Fallback ratio for desktop setups where hips aren't visible.

    Computes ``(shoulder_mid_y - nose.y) / shoulder_width`` using only
    nose + both shoulders. The 2D shoulder distance (sqrt(dx² + dy²))
    normalizes for user-camera distance: closer to camera → larger
    shoulder_width AND larger nose-to-shoulder distance, so the ratio
    stays stable. Returns ``None`` if any of the three required landmarks
    is below ``min_visibility`` or shoulders are degenerate (coincident).

    Validated empirically (2026-05-18): the diag log captured
    ``vis(nose=1.00 ls=1.00 rs=1.00 lh=0.01 rh=0.01)`` on Anthony's
    desk — shoulders + nose are at ceiling confidence even when hips
    are entirely below frame, so this fallback is reliable.
    """
    if pose_landmarks is None:
        return None
    try:
        nose = pose_landmarks[POSE_NOSE]
        ls = pose_landmarks[POSE_LEFT_SHOULDER]
        rs = pose_landmarks[POSE_RIGHT_SHOULDER]
    except (IndexError, TypeError):
        return None
    for lm in (nose, ls, rs):
        if getattr(lm, "visibility", 0.0) < min_visibility:
            return None
    shoulder_dx = rs.x - ls.x
    shoulder_dy = rs.y - ls.y
    shoulder_width = (shoulder_dx * shoulder_dx + shoulder_dy * shoulder_dy) ** 0.5
    if shoulder_width <= 1e-3:
        return None
    shoulder_mid_y = (ls.y + rs.y) / 2.0
    return (shoulder_mid_y - nose.y) / shoulder_width


def _classify_posture_from_shoulders(
    ratio: Optional[float],
    prior: Optional[str],
) -> tuple[Optional[str], Optional[float]]:
    """Same shape as ``_classify_posture`` but for the shoulder-anchored ratio.

    Sign is flipped versus head_drop:
      - HIGH ratio (head well above shoulders) → upright
      - LOW ratio (head dropped toward shoulder line) → slouched
      - Between → preserve prior commit (dead-band against flicker)
    """
    if ratio is None:
        return None, None
    confidence = min(
        1.0, abs(ratio - HEAD_ABOVE_SHOULDER_THRESHOLD_CENTER) * 5.0,
    )
    if ratio >= HEAD_ABOVE_SHOULDER_UPRIGHT_MIN:
        return POSTURE_UPRIGHT, confidence
    if ratio <= HEAD_ABOVE_SHOULDER_SLOUCHED_MAX:
        return POSTURE_SLOUCHED, confidence
    return prior, confidence if prior is not None else None

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


def _download_model(model_path: Path, url: str, label: str = "model") -> bool:
    """Fetch a MediaPipe .task file. Returns False on failure."""
    try:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s from %s ...", label, url)
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            model_path.write_bytes(resp.content)
        logger.info("%s saved (%d bytes)", label, len(resp.content))
        return True
    except Exception as exc:
        logger.error("Failed to download %s: %s", label, exc)
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
        if not _download_model(
            model_path, FACE_LANDMARKER_MODEL_URL, "FaceLandmarker model",
        ):
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


def _init_pose_landmarker() -> Optional[Any]:
    """Lazy-create a PoseLandmarker (lite) instance. Returns None on failure.

    Mirrors ``_init_face_landmarker``. The model file lives in the same
    ``data/models/`` directory; first run downloads ~5MB. Failure modes
    (mediapipe missing, download error, init exception) leave the
    posture path disabled while presence keeps working.
    """
    try:
        import mediapipe as mp
    except ImportError:
        logger.warning(
            "mediapipe not installed — desktop posture disabled"
        )
        return None

    model_path = MODEL_DIR / POSE_LANDMARKER_MODEL_FILENAME
    if not model_path.exists():
        if not _download_model(
            model_path, POSE_LANDMARKER_MODEL_URL, "PoseLandmarker model",
        ):
            return None

    try:
        BaseOptions = mp.tasks.BaseOptions
        PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        landmarker = PoseLandmarker.create_from_options(options)
        logger.info("PoseLandmarker initialized (desktop posture enabled)")
        return landmarker
    except Exception as exc:
        logger.warning("PoseLandmarker init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Capture worker
# ---------------------------------------------------------------------------


class EmotionCapture:
    """Per-frame webcam → blendshape → POST pipeline."""

    def __init__(self, server_url: str) -> None:
        self._server_url = server_url.rstrip("/")
        self._blendshape_endpoint = f"{self._server_url}/api/personality/blendshape"
        self._observation_endpoint = f"{self._server_url}/api/camera/observation"
        self._settings_endpoint = f"{self._server_url}/api/personality/settings"
        self._mode_endpoint = f"{self._server_url}/api/automation/activity"
        # Diagnostic snapshot endpoints — only hit when the backend has
        # explicitly requested a frame via POST /api/camera/desktop/snapshot/request.
        # The pending-check GET is cheap (~30 bytes) and the upload POST
        # only fires when a request is outstanding; raw frames are not
        # transmitted in normal operation.
        self._snapshot_pending_endpoint = f"{self._server_url}/api/camera/desktop/snapshot/pending"
        self._snapshot_upload_endpoint = f"{self._server_url}/api/camera/desktop/snapshot/upload"
        # Bedroom-lux endpoints (D4). The agent POSTs lux samples (Part A),
        # POSTs calibration results, and polls the calibrate-pending flag.
        self._lux_endpoint = f"{self._server_url}/api/camera/desktop/lux"
        self._lux_calibration_endpoint = f"{self._server_url}/api/camera/desktop/lux/calibration"
        self._lux_calibrate_pending_endpoint = (
            f"{self._server_url}/api/camera/desktop/lux/calibrate/pending"
        )

        # Runtime toggles, refreshed by the settings-poll thread. Defaults
        # to False so we don't capture before the user has opted in via
        # the /personality page — the supervisor restart that picks up this
        # agent is the same operation that lets the user flip the toggle.
        # `emotion` and `presence` are independent (different privacy
        # implications). Capture runs iff either is True.
        self._emotion_enabled: bool = False
        self._presence_enabled: bool = False
        # Mirrors the Latitude camera_service "pause during sleeping" behavior
        # — when mode is sleeping we release the webcam regardless of toggles
        # so the user isn't broadcasting blendshapes / presence while in bed.
        # Refreshed alongside the settings poll on the same 30s cadence.
        self._mode_is_sleeping: bool = False
        self._enabled_lock = threading.Lock()

        # Lazy-init handles
        self._cap = None
        self._landmarker = None
        self._pose_landmarker = None
        # Sticky flag — once pose init has failed in this process, don't
        # retry every 2s tick (the mediapipe import + path.exists check
        # is wasted work). Reset only when presence is toggled off-then-
        # on, which gives one more attempt per enable cycle.
        self._pose_init_failed: bool = False
        self._mp_image_cls = None  # cached mp.Image constructor

        # Posture frame-streak hysteresis. Candidate must hold for
        # POSTURE_HYSTERESIS_FRAMES consecutive ticks before
        # ``_posture_committed`` flips. Cheaper than wall-clock
        # hysteresis on the Latitude (no datetime arithmetic per tick).
        self._posture_committed: Optional[str] = None
        self._posture_candidate: Optional[str] = None
        self._posture_candidate_streak: int = 0
        self._posture_confidence: Optional[float] = None

        # Webcam-unavailable transition tracking. Mirrors the LoL
        # _note_lol_failure pattern in activity_detector.py — log a
        # single WARN on transition rather than flooding the log when
        # Zoom / Discord holds the device.
        self._last_unavailable_reason: Optional[str] = None

        # Bedroom-lux calibration (D4 Part B). The settings-poll thread sets
        # _calibrate_pending when the backend flags a calibration; the capture
        # thread (which owns _cap) runs it and clears the flag — so all webcam
        # access stays single-threaded. _lux_exposure is the calibrated fixed
        # exposure, loaded for the Part A sampler.
        self._calibrate_pending: bool = False
        self._lux_exposure: Optional[float] = None
        # Part A: monotonic timestamp of the last lux sample (None = never).
        self._last_lux_sample_at: Optional[float] = None

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
        if self._pose_landmarker is not None:
            try:
                self._pose_landmarker.close()
            except Exception:
                pass
            self._pose_landmarker = None
        try:
            self._client.close()
        except Exception:
            pass

    def _reset_posture_state(self) -> None:
        """Clear posture hysteresis state. Called when presence flips off.

        Also clears the sticky pose-init-failed flag so a disable / re-
        enable cycle gets one more attempt — useful if the user installs
        mediapipe or unblocks the model URL while the agent is running.
        """
        self._posture_committed = None
        self._posture_candidate = None
        self._posture_candidate_streak = 0
        self._posture_confidence = None
        self._pose_init_failed = False

    # ── enable flags ────────────────────────────────────────────────

    def set_enabled(
        self,
        *,
        emotion: Optional[bool] = None,
        presence: Optional[bool] = None,
    ) -> None:
        """Update either toggle (or both). Logs only on transitions."""
        with self._enabled_lock:
            if emotion is not None and emotion != self._emotion_enabled:
                logger.info("desktop_emotion_enabled → %s", emotion)
                self._emotion_enabled = emotion
            if presence is not None and presence != self._presence_enabled:
                logger.info("desktop_presence_enabled → %s", presence)
                self._presence_enabled = presence
                if not presence:
                    # Clear hysteresis so the next enable starts cleanly
                    # — old posture commit shouldn't survive a disable
                    # cycle (user may have left/returned in between).
                    self._reset_posture_state()

    def is_capture_needed(self) -> bool:
        """True if any consumer is enabled AND mode isn't sleeping."""
        with self._enabled_lock:
            if self._mode_is_sleeping:
                return False
            return self._emotion_enabled or self._presence_enabled

    def set_mode_sleeping(self, sleeping: bool) -> None:
        """Update the sleeping-mode gate. Logs only on transitions."""
        with self._enabled_lock:
            if sleeping != self._mode_is_sleeping:
                logger.info("mode_is_sleeping → %s (gate)", sleeping)
                self._mode_is_sleeping = sleeping

    def is_emotion_enabled(self) -> bool:
        with self._enabled_lock:
            return self._emotion_enabled

    def is_presence_enabled(self) -> bool:
        with self._enabled_lock:
            return self._presence_enabled

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
            # CAP_DSHOW (DirectShow) over the default MSMF backend: on the
            # Logitech Brio, MSMF intermittently hangs on open and stalls the
            # stream (the LED-cycling "can't see me" failure, 2026-06-01).
            # DSHOW opens reliably and is the only backend that controls
            # exposure on this cam — which the D4 lux work also needs.
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                self._note_webcam_unavailable("open_failed")
                cap.release()
                return False
            # Force AUTO exposure on every open. The Brio retains exposure
            # state in firmware across handle opens; the D4 exposure spike
            # left it pinned manual-dark (EXPOSURE=-10), blacking out face
            # detection until reset. 0.75 = auto in DirectShow's convention.
            # Defensive: a stray manual state can never persist into presence
            # capture again. (D4 will flip to a fixed exposure only briefly
            # per lux sample, then restore auto here.)
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, EXPOSURE_AUTO)
            except Exception:
                pass
            self._cap = cap
            logger.info("Webcam opened (cv2.VideoCapture(0, CAP_DSHOW))")
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
        if not self.is_capture_needed():
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

        # Bedroom-lux calibration (D4 Part B) runs on THIS thread (it owns
        # _cap). A deliberate user-triggered exposure sweep (~15s) — skip the
        # normal presence capture for this tick; _run_lux_calibration always
        # restores auto-exposure so capture resumes next tick.
        if self._take_calibrate_pending():
            self._run_lux_calibration(cv2)
            return

        # Bedroom-lux sampling (D4 Part A) — periodic flip-sample-flip. A brief
        # (~1s) switch to the calibrated fixed exposure for one lux reading,
        # then restore auto. Skips THIS tick's presence POST so the dark
        # fixed-exposure frames never register as "no face". Gated on a
        # calibrated exposure existing.
        if self._should_sample_lux(time.monotonic()):
            self._sample_lux(cv2)
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

            # Derive face_present + face_confidence even when no blendshapes
            # were returned. FaceLandmarker has no top-level detector
            # score; the max non-neutral blendshape activation is the
            # established proxy. Empty list → confidence 0 → not present.
            if face_blendshapes:
                shapes = face_blendshapes[0]
                blendshape_dict = {
                    cat.category_name: float(cat.score) for cat in shapes
                }
                face_confidence = max(
                    (
                        score
                        for name, score in blendshape_dict.items()
                        if name != "_neutral"
                    ),
                    default=0.0,
                )
            else:
                blendshape_dict = {}
                face_confidence = 0.0

            face_present = face_confidence >= FACE_CONFIDENCE_FLOOR
            captured_at = datetime.now(timezone.utc)

            # Diagnostic snapshot — opt-in, backend-initiated. Fires
            # regardless of face presence (the truth-table walk needs
            # to capture what the camera sees from positions where
            # the desktop can't detect a face — bed, kitchen, etc.).
            # Privacy-gated server-side via the pending flag.
            self._maybe_upload_snapshot(
                frame=frame,
                face_present=face_present,
                face_confidence=face_confidence,
                captured_at=captured_at,
                cv2=cv2,
            )

            # Pose classification — only when presence is enabled and
            # we have a face (no point classifying posture for an empty
            # chair). The pose detector + classifier are pure additions
            # to the existing capture cycle; FaceLandmarker remains the
            # primary gate.
            posture: Optional[str] = None
            posture_confidence: Optional[float] = None
            if self.is_presence_enabled() and face_present:
                posture, posture_confidence = self._classify_pose(mp_image)

            # Presence is independent of emotion — POST even when face is
            # below the emotion floor, so the backend has an unambiguous
            # absent signal. Skip only when the toggle is off.
            if self.is_presence_enabled():
                self._post_observation(
                    face_present=face_present,
                    face_confidence=face_confidence,
                    captured_at=captured_at,
                    posture=posture,
                    posture_confidence=posture_confidence,
                )

            if not face_present:
                return

            if self.is_emotion_enabled():
                self._post_blendshapes(
                    blendshape_dict, face_confidence, captured_at=captured_at,
                )
        finally:
            # Explicit dereference so the numpy buffers go out of scope
            # before the next tick — mirrors camera_service's finally pattern.
            frame = None
            rgb = None

    def _classify_pose(self, mp_image: Any) -> tuple[Optional[str], Optional[float]]:
        """Run pose inference + classify + apply frame-streak hysteresis.

        Returns the committed posture + confidence (None on either if
        the pose model isn't healthy, landmarks aren't visible, or the
        candidate hasn't held long enough). Lazy-initializes the pose
        landmarker on the first eligible call; failure stays sticky
        (per ``_pose_init_failed``) until presence is toggled off-then-on.
        """
        if self._pose_init_failed:
            return None, None
        if self._pose_landmarker is None:
            self._pose_landmarker = _init_pose_landmarker()
            if self._pose_landmarker is None:
                # Init failed — set the sticky flag so subsequent ticks
                # don't pay the mediapipe-import + model-path-stat cost
                # again. Cleared on the next disable/enable cycle.
                self._pose_init_failed = True
                return None, None

        try:
            pose_result = self._pose_landmarker.detect(mp_image)
        except Exception:
            logger.debug("PoseLandmarker.detect failed", exc_info=True)
            return None, None

        pose_landmarks_list = getattr(pose_result, "pose_landmarks", None) or []
        if not pose_landmarks_list:
            # No torso detected this frame. Don't decay the committed
            # value here — a single missed frame during a stable session
            # shouldn't erase posture. The streak logic below will
            # eventually transition to None if absences sustain.
            self._update_posture_candidate(None, None)
            return self._posture_committed, self._posture_confidence

        # Primary classifier: hip-anchored head-drop ratio. When hips
        # are visible this is the most distance-invariant signal. The
        # Latitude's mounting + framing typically clears the hip
        # visibility floor; the desktop's frontal-close-range view
        # frequently doesn't (desk lip / camera-above-monitor geometry).
        head_drop = _compute_head_drop_ratio(pose_landmarks_list[0])
        if head_drop is not None:
            candidate, confidence = _classify_posture(
                head_drop, prior=self._posture_committed,
            )
        else:
            # Fallback: shoulder-anchored ratio for setups where hips
            # aren't visible. Uses only nose + both shoulders, both of
            # which the desktop frontal view captures at ceiling
            # confidence (validated 2026-05-18 via the temporary
            # pose-diag log path; thresholds calibrated from that pass).
            ratio = _compute_head_above_shoulders_ratio(
                pose_landmarks_list[0],
            )
            candidate, confidence = _classify_posture_from_shoulders(
                ratio, prior=self._posture_committed,
            )
        self._update_posture_candidate(candidate, confidence)
        return self._posture_committed, self._posture_confidence

    def _update_posture_candidate(
        self,
        candidate: Optional[str],
        confidence: Optional[float],
    ) -> None:
        """Apply frame-streak hysteresis to a per-tick classifier result.

        - If the candidate matches the committed value: no transition;
          refresh confidence and reset the streak counter.
        - If it differs (including transitions to/from None): start /
          continue counting consecutive matching frames. Once the
          streak hits POSTURE_HYSTERESIS_FRAMES, commit.
        """
        if candidate == self._posture_committed:
            self._posture_candidate = None
            self._posture_candidate_streak = 0
            if confidence is not None:
                self._posture_confidence = confidence
            return

        if candidate == self._posture_candidate:
            self._posture_candidate_streak += 1
        else:
            self._posture_candidate = candidate
            self._posture_candidate_streak = 1

        if self._posture_candidate_streak >= POSTURE_HYSTERESIS_FRAMES:
            logger.debug(
                "Posture commit: %s → %s (streak=%d, conf=%s)",
                self._posture_committed,
                candidate,
                self._posture_candidate_streak,
                confidence,
            )
            self._posture_committed = candidate
            self._posture_confidence = confidence
            self._posture_candidate = None
            self._posture_candidate_streak = 0

    def _post_blendshapes(
        self,
        blendshapes: dict[str, float],
        face_confidence: float,
        captured_at: Optional[datetime] = None,
    ) -> None:
        payload = {
            "blendshapes": blendshapes,
            "face_confidence": face_confidence,
            "source": "desktop",
            "timestamp": (captured_at or datetime.now(timezone.utc)).isoformat(),
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

    def _post_observation(
        self,
        *,
        face_present: bool,
        face_confidence: float,
        captured_at: datetime,
        posture: Optional[str] = None,
        posture_confidence: Optional[float] = None,
    ) -> None:
        """POST one PresenceReading to the backend.

        Best-effort — transient network errors are logged at DEBUG and
        the next tick will fire 2s later. Mirrors the blendshape POST
        error-handling (the agent shouldn't crash on a backend blip).

        ``posture`` and ``posture_confidence`` are included only when
        non-None so the backend payload stays small when the pose path
        is unhealthy (model missing, hips not visible, etc.).
        """
        payload: dict[str, Any] = {
            "source": "desktop",
            "captured_at": captured_at.isoformat(),
            "face_present": face_present,
            "face_confidence": face_confidence,
            "detection_source": "face",
        }
        # Explicit desk-zone assertion. The frontal FaceLandmarker only fires
        # on a close-range face at the monitor, so a positive face_present
        # localizes the user to the desk. Emitting zone="desk" (rather than
        # leaving PresenceFusion to infer it from face_present) makes the
        # desktop a first-class desk-zone source — load-bearing once the
        # Latitude relocates to the living room and stops reporting desk/bed.
        if face_present:
            payload["zone"] = "desk"
        if posture is not None:
            payload["posture"] = posture
        if posture_confidence is not None:
            payload["posture_confidence"] = posture_confidence
        try:
            resp = self._client.post(self._observation_endpoint, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "POST /observation returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.debug("POST /observation failed: %s", exc)

    def _maybe_upload_snapshot(
        self,
        *,
        frame: Any,
        face_present: bool,
        face_confidence: float,
        captured_at: datetime,
        cv2: Any,
    ) -> None:
        """If the backend has a pending snapshot request, ship the frame.

        Backend-driven: we only encode + POST when /desktop/snapshot/pending
        returns ``pending=True``. That route is gated by an explicit
        diagnostic call to /desktop/snapshot/request — raw frames never
        leave this host in normal operation.

        Privacy gate: enforced on the desktop side via ``is_presence_enabled``.
        The emotion-only toggle never lets a raw frame leave the host
        even if the backend mistakenly sets the pending flag (defense in
        depth — backend already double-checks, but we don't want the
        contract to rest on a single point of agreement).

        Best-effort. Pending-check network error → silent retry next tick.
        Encode error → log + skip (next tick will retry while pending
        remains set). Upload error → log; the backend will keep the flag
        set until TTL expiry, so a transient blip auto-recovers.
        """
        if not self.is_presence_enabled():
            return
        # Cheap pending probe first so we don't encode every tick.
        try:
            resp = self._client.get(
                self._snapshot_pending_endpoint, timeout=HTTP_TIMEOUT_S,
            )
            if resp.status_code != 200:
                return
            body = resp.json()
        except (httpx.HTTPError, ValueError):
            return
        if not bool(body.get("pending")):
            return

        # Encode the current BGR frame to JPEG. cv2.imencode returns
        # (success: bool, ndarray) — we send the ndarray bytes directly
        # without ever writing to disk on the desktop side.
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok or buf is None:
                logger.warning("cv2.imencode returned no buffer for snapshot")
                return
            jpeg_bytes = buf.tobytes()
        except Exception:
            logger.warning("Snapshot encode failed", exc_info=True)
            return

        files = {
            "image": ("desktop_snapshot.jpg", jpeg_bytes, "image/jpeg"),
        }
        data = {
            "captured_at": captured_at.isoformat(),
            "face_present": "true" if face_present else "false",
            "face_confidence": f"{face_confidence:.4f}",
        }
        try:
            up = self._client.post(
                self._snapshot_upload_endpoint,
                files=files,
                data=data,
                timeout=HTTP_TIMEOUT_S * 2,  # JPEG is ~50–200 KB
            )
            if up.status_code >= 400:
                logger.warning(
                    "POST /desktop/snapshot/upload returned %d: %s",
                    up.status_code,
                    up.text[:200],
                )
            else:
                logger.info(
                    "Desktop snapshot uploaded (%d bytes)", len(jpeg_bytes),
                )
        except httpx.HTTPError as exc:
            logger.warning("Snapshot upload failed: %s", exc)

    # ── bedroom-lux calibration (D4 Part B) ─────────────────────────

    def _take_calibrate_pending(self) -> bool:
        """Atomically read-and-clear the calibrate-pending flag.

        Consume-on-take: the request is cleared when picked up, so a
        transient read failure during calibration loses the request and the
        user re-triggers (deliberate UI action with feedback). Keeps webcam
        access single-threaded — only the capture thread touches ``_cap``.
        """
        with self._enabled_lock:
            if self._calibrate_pending:
                self._calibrate_pending = False
                return True
            return False

    def _run_lux_calibration(self, cv2: Any) -> None:
        """Sweep exposure → ``gray.mean()≈target`` under current bedroom light,
        then POST ``{exposure, baseline_lux}``.

        Runs on the capture thread (owns ``_cap``). Full-frame mean (no zone
        weighting — D4 micro-decision). ALWAYS restores auto-exposure in a
        ``finally`` so presence capture resumes — never leave the Brio pinned
        manual (the 2026-06-01 black-out failure, see
        ``project_desktop_webcam_dshow``).
        """

        cap = self._cap
        if cap is None or not cap.isOpened():
            logger.warning("Lux calibration skipped — webcam not open")
            return
        logger.info("Bedroom lux calibration starting (exposure sweep)...")
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, EXPOSURE_MANUAL)

            def measure(exposure: float) -> float:
                # Set exposure, let auto-gain settle, then take a poll-cadence
                # measurement (mirrors camera_service so the baseline matches
                # what a live sampler would read).
                cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
                time.sleep(3.0)
                cap.read()  # drop the first frame after settle
                vals: list[float] = []
                for _ in range(3):
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        vals.append(
                            float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
                        )
                    time.sleep(0.5)
                return sum(vals) / len(vals) if vals else -1.0

            exposure, measured = search_exposure(measure)
        finally:
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, EXPOSURE_AUTO)
            except Exception:
                pass

        if measured < 0:
            logger.warning(
                "Lux calibration failed (camera read) — re-request to retry",
            )
            return
        if not (LUX_ACCEPT_LO <= measured <= LUX_ACCEPT_HI):
            logger.warning(
                "Lux calibration: room mean %.1f outside [%.0f,%.0f] — too %s; "
                "recalibrate at comfortable-bright bedroom light",
                measured, LUX_ACCEPT_LO, LUX_ACCEPT_HI,
                "dark" if measured < LUX_ACCEPT_LO else "bright",
            )
        self._lux_exposure = exposure
        self._post_lux_calibration(exposure, measured)
        logger.info(
            "Bedroom lux calibration done: exposure=%.1f baseline=%.1f",
            exposure, measured,
        )

    def _post_lux_calibration(self, exposure: float, baseline_lux: float) -> None:
        """POST the calibration result; the backend persists it + clears the flag."""
        payload = {
            "exposure": round(exposure, 2),
            "baseline_lux": round(baseline_lux, 1),
            "target_lux": LUX_CALIBRATION_TARGET,
        }
        try:
            resp = self._client.post(self._lux_calibration_endpoint, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "POST /lux/calibration returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.warning("POST /lux/calibration failed: %s", exc)

    # ── bedroom-lux sampling (D4 Part A) ────────────────────────────

    def _should_sample_lux(self, now_monotonic: float) -> bool:
        """True iff it's time for a lux sample.

        Requires a calibrated exposure (``_lux_exposure`` set, loaded from
        ``desktop_lux_calibration_config``) and that at least
        ``LUX_SAMPLE_INTERVAL_S`` has passed since the last sample. Pure given
        ``now_monotonic`` so the cadence is unit-testable without a clock.
        """
        if self._lux_exposure is None:
            return False
        if self._last_lux_sample_at is None:
            return True
        return (now_monotonic - self._last_lux_sample_at) >= LUX_SAMPLE_INTERVAL_S

    def _sample_lux(self, cv2: Any) -> None:
        """Flip to the calibrated fixed exposure, read one lux value, restore auto.

        Runs on the capture thread (owns ``_cap``). Full-frame ``gray.mean()``
        (D4 micro-decision). ALWAYS restores auto-exposure in a ``finally`` —
        on the SAME handle, since ``_ensure_cap`` only force-autos on *open*
        (see ``project_desktop_webcam_dshow``). Stamps ``_last_lux_sample_at``
        even on failure so a wedged read doesn't hot-loop the sampler.
        """
        self._last_lux_sample_at = time.monotonic()
        cap = self._cap
        exposure = self._lux_exposure
        if cap is None or not cap.isOpened() or exposure is None:
            return
        lux: Optional[float] = None
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, EXPOSURE_MANUAL)
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            time.sleep(LUX_SAMPLE_SETTLE_S)
            cap.read()  # drop the first post-switch frame
            vals: list[float] = []
            for _ in range(LUX_SAMPLE_FRAMES):
                ok, frame = cap.read()
                if ok and frame is not None:
                    vals.append(
                        float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
                    )
            if vals:
                lux = sum(vals) / len(vals)
        finally:
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, EXPOSURE_AUTO)
            except Exception:
                pass
        if lux is None:
            logger.debug("Lux sample skipped — no frame read")
            return
        self._post_lux(lux)

    def _post_lux(self, ambient_lux: float) -> None:
        """POST one ambient-lux sample to the bedroom channel. Best-effort."""
        payload = {
            "ambient_lux": round(ambient_lux, 1),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = self._client.post(self._lux_endpoint, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "POST /desktop/lux returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
        except httpx.HTTPError as exc:
            logger.debug("POST /desktop/lux failed: %s", exc)

    # ── settings poll ───────────────────────────────────────────────

    def poll_settings(self) -> None:
        """Refresh the enabled flag from /api/personality/settings.

        On transient errors (network blip, backend restart) we leave the
        current flag alone — better than going silent during a deploy.
        Also refreshes the sleeping-mode gate from /api/automation/activity
        so the desktop cam releases when the apartment goes to sleep.
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
        emotion_flag = bool(data.get("desktop_emotion_enabled"))
        presence_flag = bool(data.get("desktop_presence_enabled"))
        # Presence is gated on personality_enabled too — same opt-in flow.
        # Either sub-toggle being on is enough to start the capture loop.
        self.set_enabled(
            emotion=personality and emotion_flag,
            presence=personality and presence_flag,
        )

        # Sleeping-mode gate — /api/automation/activity returns a 2-field
        # payload ({mode, source}) and is unauthenticated. Transient errors
        # leave the prior gate state alone (same policy as settings above).
        try:
            mode_resp = self._client.get(self._mode_endpoint)
            mode_resp.raise_for_status()
            mode_data = mode_resp.json()
        except httpx.HTTPError as exc:
            logger.debug("Mode poll failed: %s", exc)
            return
        except ValueError:
            logger.debug("Mode poll returned non-JSON")
            return
        mode = (mode_data.get("mode") or "").lower()
        self.set_mode_sleeping(mode == "sleeping")

        # Bedroom-lux calibration request (D4 Part B). Cheap flag poll on the
        # same 30s cadence; the capture thread actually runs the sweep. Only
        # flips the flag on (the capture thread consumes + clears it), so a
        # missed poll just delays calibration to the next cycle.
        try:
            cal_resp = self._client.get(self._lux_calibrate_pending_endpoint)
            if cal_resp.status_code == 200 and bool(cal_resp.json().get("pending")):
                with self._enabled_lock:
                    self._calibrate_pending = True
        except (httpx.HTTPError, ValueError):
            pass

        # Load the calibrated exposure (D4 Part A) so the sampler can pin it.
        # Lives in app_settings, so this survives an agent restart (the
        # in-process _lux_exposure set during a calibration run is the live
        # path; this GET is the cold-start / cross-session path).
        try:
            cfg_resp = self._client.get(self._lux_calibration_endpoint)
            if cfg_resp.status_code == 200:
                exp = cfg_resp.json().get("exposure")
                if exp is not None:
                    self._lux_exposure = float(exp)
        except (httpx.HTTPError, ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Threaded supervisor entry point
# ---------------------------------------------------------------------------


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> None:
    """Supervisor entry point. Runs capture + settings polling until stopped.

    Mirrors the signature of activity_detector.run_agent so the
    supervisor's AgentState dispatcher can drop this in without special
    casing. The capture and settings loops share the same stop_event,
    so a single supervisor stop tears down both.

    `heartbeat` (injected by the supervisor) is pulsed at the top of each
    capture iteration; if it stops — e.g. a wedged cv2 read leaves the thread
    alive but blocked — the supervisor detects the stale beat and recovers.
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
            if heartbeat is not None:
                heartbeat()
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
        default="http://192.168.86.210:8000",
        help="Home Hub server URL (default: http://192.168.86.210:8000)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    run_agent(args.server)
