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
    python -m backend.services.pc_agent.emotion_capture --server http://192.168.1.210:8000
"""
import argparse
import logging
import signal
import sys
import threading
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


# ---------------------------------------------------------------------------
# Pure classifier helpers (testable without MediaPipe installed)
# ---------------------------------------------------------------------------


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

        # Runtime toggles, refreshed by the settings-poll thread. Defaults
        # to False so we don't capture before the user has opted in via
        # the /personality page — the supervisor restart that picks up this
        # agent is the same operation that lets the user flip the toggle.
        # `emotion` and `presence` are independent (different privacy
        # implications). Capture runs iff either is True.
        self._emotion_enabled: bool = False
        self._presence_enabled: bool = False
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
        """True if any consumer is currently enabled."""
        with self._enabled_lock:
            return self._emotion_enabled or self._presence_enabled

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

            face_present = face_confidence >= FACE_CONFIDENCE_FLOOR
            captured_at = datetime.now(timezone.utc)

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
        emotion_flag = bool(data.get("desktop_emotion_enabled"))
        presence_flag = bool(data.get("desktop_presence_enabled"))
        # Presence is gated on personality_enabled too — same opt-in flow.
        # Either sub-toggle being on is enough to start the capture loop.
        self.set_enabled(
            emotion=personality and emotion_flag,
            presence=personality and presence_flag,
        )


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
