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
import hashlib
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from fastapi import FastAPI

    from backend.services.presence_fusion import PresenceReading

logger = logging.getLogger("home_hub.camera")

# Polling and detection constants
POLL_INTERVAL = 2       # Seconds between frame captures
# Watchdog: bound the blocking _process_frame executor call so a hung
# V4L2 read() can't silently freeze the entire poll loop. Picked at ~2.5x
# POLL_INTERVAL — long enough for an honest slow MediaPipe frame, short
# enough that a real hang is detected within a single iteration.
FRAME_READ_TIMEOUT_S = 5.0
# Bound the blocking capture *open* (cv2.VideoCapture(0) + warm-up read +
# any release of a prior handle) off the event loop. The open runs in an
# executor wrapped in asyncio.wait_for(this); on timeout we treat the camera
# as unavailable rather than letting a wedged V4L2 open freeze the whole
# backend (lights/Sonos/WS run on the same loop) or park the supervisor that
# is supposed to recover it (the 2026-05-27 watchdog self-silencing). Picked
# above CAP_OPEN_TIMEOUT_MS so OpenCV's own open timeout fires first when it
# works, with this as the hard backstop for a driver that ignores it.
CAP_OPEN_WATCHDOG_SECONDS = 6.0
# V4L2 capture timeouts. Set on the cv2.VideoCapture handle at open time;
# OpenCV ignores these on backends that don't support them, so they're
# safe to set unconditionally. CAP_READ_TIMEOUT_MSEC is the primary defense
# against the post-resume hang we saw on 2026-04-30.
CAP_OPEN_TIMEOUT_MS = 3000
CAP_READ_TIMEOUT_MS = 2000
# 640x480 gives BlazeFace enough pixel detail to score Anthony's profile view
# at 2-3m (corner position) noticeably higher than 320x240 did. Pose landmarker
# was already solid at the lower resolution; face scores are the beneficiary.
# Lux calibration (exposure + baseline_lux) MUST be re-run after any change to
# these constants — gray.mean() at the new pixel count will differ from the
# value the stored baseline was recorded at.
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
# Fifteen consecutive misses (~30s) before flipping to idle. Extended past
# the original seven (~14s) after a live low-light scenario (reading in bed
# at ema_lux ~30, 20% of baseline) showed face/pose detection flapping 25-40%
# and the mode flipping on brief misses. Brief dropouts in dim light are the
# common case, not the exception, so we want more dampening.
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
# Stricter floor for the *weak-face-only* fallback under low ambient light.
# At ema_lux < LOW_LUX_THRESHOLD the chair-back / picture-frame silhouettes
# routinely produce 0.15–0.25 face scores that re-emit `present` between
# real Anthony cycles, defeating downstream services that watch for sustained
# absence (TransitLightingService, DeskExitKitchenService). This floor only
# gates the weak path: strong face (≥ FACE_TRUST_THRESHOLD) and pose still
# fire normally regardless of lux. Evidence (2026-05-18 05:08 ET): Anthony
# walked off-frame, chair-back held face at 0.18 conf @ ema_lux 151 — the
# camera flapped present/absent and the downstream absent dwell never
# stabilized. Pose detection (which has its own torso-visibility gate) is
# unaffected.
LOW_LUX_FACE_FLOOR_CONF = 0.25
LOW_LUX_THRESHOLD = 300.0
# Face confidence above which face wins outright over pose. Below this, when
# pose is strong, pose takes priority — this protects against face-like
# furniture silhouettes (chair backs, accent chair) competing with the real
# face for `max(detections, key=score)` selection. Observed chair-back vs
# real-face range during the 2026-05-05 oscillation incident was 0.16–0.65,
# so the bar sits above the chair-back ceiling. Real desk sessions in good
# lighting typically clear 0.7–0.85.
FACE_TRUST_THRESHOLD = 0.70
# Face-anchor cross-validation for pose detections. MediaPipe pose fires at
# 0.98 confidence with full landmark visibility on the empty office chair
# (symmetric back + armrests + headrest reads as a human torso) — observed
# 2026-05-21 truth-table walk, see project_latitude_pose_on_chair_false_positive.md.
# To distinguish a real user (whose face we saw recently) from furniture
# (which never has a face), require a face anchor within the TTL window
# before honoring a pose-only present commit. The anchor refreshes whenever
# a face fires above ``FACE_ANCHOR_MIN_CONFIDENCE`` in the same zone — so a
# user who sat down, was face-detected, then turned to the side monitor
# (face-less but still in the chair) keeps committing pose-present as long
# as the side-glance is shorter than the TTL.
#
# Threshold + window choice:
#   - 0.40 is comfortably above MIN_FACE_CONFIDENCE (0.15, chair-back territory)
#     but well below FACE_TRUST_THRESHOLD (0.70, the strong-face bar). It admits
#     real-but-imperfect frontal face reads while excluding silhouette noise.
#   - 30s is long enough to cover a real "turn to look at the printer / side
#     monitor" event without committing pose-only state indefinitely. End-to-
#     end DeskExitKitchenService latency after a true walkout: anchor expires
#     at 30s → pose-only stops committing → DeskExit absent timer (10s) →
#     kitchen brightens at ~40s post-walkout.
FACE_ANCHOR_MIN_CONFIDENCE = 0.40
FACE_ANCHOR_TTL_SECONDS = 30.0
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

# Zone mapping. 2026-05-27: the Latitude relocated from the bedroom corner
# (which split desk left / bed right along ZONE_DESK_THRESHOLD) to the living
# room, where it frames a single area — the couch. It now emits one zone,
# ZONE_COUCH, for any confident detection; the left/right split was bedroom
# geometry and no longer maps to anything meaningful. "At desk" presence is
# now owned by the desktop pc_agent (PresenceFusion), which sees the user
# frontally at the monitor. ZONE_DESK / ZONE_BED are retained as constants
# because the desktop source + PresenceFusion fallbacks still reference them.
ZONE_DESK = "desk"
ZONE_BED = "bed"
ZONE_COUCH = "couch"
# Normalized X (detected center / frame width). Corner view places desk
# around ~0.15 and bed roughly 0.4–0.9; 0.40 catches the accent-chair
# transition region. Hysteresis (below) absorbs brief crossings.
ZONE_DESK_THRESHOLD = 0.40
# A new candidate zone must hold this many seconds before it replaces the
# committed zone. 15s matches the "sustained detection" character of the
# absent threshold (7 frames × 2s poll ≈ 14s).
ZONE_HYSTERESIS_SECONDS = 15


def _zone_weighted_lux(gray, zone: Optional[str]) -> float:
    """Sample mean intensity from the frame half matching the user's zone.

    Frame-level mean was producing perception-mismatched readings: a
    bright bed-side wall pulled the average up while the user's desk-side
    area was dim. Sampling only the active zone's half tracks the user's
    actual perceptual environment. Falls back to full-frame when zone is
    unknown (no commit yet, or just-resumed). The split mirrors
    ``ZONE_DESK_THRESHOLD`` so lux and zone-detection share a boundary.

    The living-room ``ZONE_COUCH`` (2026-05-27 relocation) intentionally
    uses the full frame — the whole view is the couch/living area, so there
    is no sub-region to isolate; it falls through to the full-frame mean.
    """
    width = gray.shape[1]
    split = int(ZONE_DESK_THRESHOLD * width)
    if zone == ZONE_DESK:
        return float(gray[:, :split].mean())
    if zone == ZONE_BED:
        return float(gray[:, split:].mean())
    return float(gray.mean())

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
# Higher visibility floor for HIP landmarks specifically. MediaPipe Pose
# extrapolates occluded landmarks with visibility ≥0.5 — at the desk
# the hips hide behind the monitor/chair and the extrapolated values
# collapse to ~shoulder_y, producing a near-zero delta and a false
# "reclined" classification. Truly-visible hips score 0.95+; 0.8 keeps
# real readings and rejects extrapolations.
MIN_POSE_VISIBILITY_HIP = 0.8
# Anatomical floor on the hip-shoulder Y delta. Real reclined posture
# (Anthony in profile) produces ~0.05; values below that are geometrically
# implausible — extrapolated/collapsed landmarks. Return None and let
# hysteresis preserve the prior commit rather than emit a false reclined.
POSTURE_MIN_ANATOMICAL_DELTA = 0.05
# Hysteresis mirrors the zone rule (15s sustained before commit).
POSTURE_HYSTERESIS_SECONDS = 15

# Ambient lux calibration constants. Auto-exposure is disabled when a
# calibration is present so gray.mean() reflects actual room brightness
# instead of the webcam compensating with its aperture.
EXPOSURE_TARGET_LUX = 100   # Target frame mean at calibration time
EXPOSURE_TOLERANCE = 10     # Accept calibration within target ± tolerance
CALIBRATION_FRAMES = 10     # Frames averaged per exposure probe
LUX_EMA_ALPHA = 0.3         # Smoothing factor (α*raw + (1-α)*ema) — ~20s to 95%
# How long the EMA may sit untouched (e.g. all-night sleeping pause, all-day
# absence) before the next reading should snap rather than blend. Without
# this the first post-pause frame is averaged with yesterday's room light
# and the multiplier swings the full +30%/-15% range while the EMA catches up.
LUX_EMA_STALE_RESET_SECONDS = 300
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
# Pinned MD5s of MediaPipe model bytes. Google's CDN only exposes a
# single `latest/` pointer per model — there's no versioned URL we can
# lock to. These hashes are the integrity gate against (1) silent CDN
# regressions (Google republishes a worse model under the same URL) and
# (2) on-disk corruption. Captured 2026-05-20 from the live production
# files. Mismatch semantics differ per model: face detection is hard-
# fail (camera lane stays cold, watchdog reports degraded), pose +
# face_landmarker are soft-fail (the respective feature is disabled but
# the rest of the camera service still runs). Emergency bypass for all
# three: HOME_HUB_SKIP_MODEL_HASH_CHECK=1.
EXPECTED_FACE_MODEL_MD5 = "5de376fcc855273c5c720766d36523a0"  # CDN Last-Modified 2026-03-11
EXPECTED_POSE_MODEL_MD5 = "04a75ddf7c811ac7a1a4523266dd7d88"  # CDN Last-Modified 2023-04-27
EXPECTED_FACE_LANDMARKER_MODEL_MD5 = "b0e7274907a1644404fef66b28dd6d85"  # CDN Last-Modified 2023-05-03
# Pose Landmarker (lite variant ≈ 5 MB). Runs only when face detection
# misses in the poll loop, and always during snapshot annotation.
POSE_MODEL_FILENAME = "pose_landmarker_lite.task"
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)

# Face Landmarker — 478 landmarks + 52 ARKit blendshapes. Runs IN PARALLEL
# with the existing FaceDetector (not as a replacement) and only when
# emotion_enabled is True. The personality layer subscribes to the
# blendshape callback to produce its mood vector. ~3MB model, ~20ms per
# frame at 640×480 on the Latitude CPU.
FACE_LANDMARKER_MODEL_FILENAME = "face_landmarker.task"
FACE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/"
    "face_landmarker.task"
)
# Minimum face confidence (from the existing BlazeFace pass) below which
# we don't even bother running the landmarker. Same threshold the
# EmotionService uses to gate its EMA update — keeps the two consistent
# without coupling.
FACE_LANDMARKER_TRIGGER_CONFIDENCE = 0.30


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
        # FaceLandmarker is lazy-loaded the first time emotion_enabled
        # flips True. Keeps the cold-start path lean for the common case
        # where personality features are off. See set_emotion_enabled().
        self._face_landmarker = None
        self._emotion_enabled: bool = False
        self._blendshape_callbacks: list = []
        # PresenceFusion (or any tagged-source consumer) registers here.
        # Fired after each poll-loop frame with a complete PresenceReading
        # so the fusion layer can merge Latitude + desktop observations.
        self._observation_callbacks: list = []

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

        # Face anchor — last time a face fired in each zone with confidence
        # >= FACE_ANCHOR_MIN_CONFIDENCE. Gates pose-only present commits so
        # the empty office chair (which fires pose at 0.98) doesn't masquerade
        # as the user. See FACE_ANCHOR_MIN_CONFIDENCE / FACE_ANCHOR_TTL_SECONDS
        # docs above.
        self._face_anchor_at: dict[str, datetime] = {}

        # Heartbeat registry — set via set_heartbeat_registry from lifespan.
        # Camera is opt-in, so we register only on enable and deregister on
        # disable / pause to avoid false-flagging legitimate downtime.
        self._heartbeat = None

        # poll_loop task handle — set by the spawner (bootstrap or the
        # API/watchdog respawn path). close() cancels and awaits it so a
        # respawn doesn't leave an orphan loop ticking against a released
        # capture handle.
        self._poll_task: Optional[asyncio.Task] = None

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

    # ------------------------------------------------------------------
    # Personality / emotion hooks (Phase A — face blendshapes)
    #
    # EmotionService subscribes to blendshape callbacks here. Only fired
    # when emotion_enabled is True AND a confident face is detected on
    # the current frame. Same in-memory-only contract as pose landmarks:
    # blendshape values are floats derived from the face crop inside
    # this executor and never persisted as raw frame data.
    # ------------------------------------------------------------------

    def register_blendshape_callback(self, callback) -> None:
        """Subscribe to per-frame blendshape readings.

        Callback signature: ``async def cb(blendshapes: dict[str, float],
        face_confidence: float, timestamp: datetime) -> None``. Async
        callbacks are scheduled on the running loop; sync callbacks run
        inline (kept fast).
        """
        if callback not in self._blendshape_callbacks:
            self._blendshape_callbacks.append(callback)

    def register_observation_callback(
        self, callback: "Callable[[PresenceReading], None]",
    ) -> None:
        """Subscribe to per-frame Latitude presence observations.

        Sync callbacks only — PresenceFusion's ``on_observation`` is the
        canonical consumer and is intentionally sync (dict assignment).
        Fires after zone/posture hysteresis has settled so the reading
        carries the just-committed values, not the candidates.
        """
        if callback not in self._observation_callbacks:
            self._observation_callbacks.append(callback)

    def set_emotion_enabled(self, enabled: bool) -> None:
        """Flip the per-frame FaceLandmarker pass on or off.

        Lazy-loads the landmarker model the first time we flip ON. If
        the model load fails we log + stay disabled (face presence keeps
        working, only emotion is gated).
        """
        enabled = bool(enabled)
        if enabled == self._emotion_enabled:
            return
        self._emotion_enabled = enabled
        if enabled and self._face_landmarker is None:
            self._init_face_landmarker()
        if enabled and self._face_landmarker is None:
            # init failed — stay off so the per-frame path doesn't try
            self._emotion_enabled = False
            logger.warning(
                "Emotion enabled requested but FaceLandmarker init failed; "
                "staying disabled"
            )

    def _init_face_landmarker(self) -> None:
        """Best-effort lazy load of FaceLandmarker. No-op on failure."""
        try:
            import mediapipe as mp
        except ImportError:
            logger.warning("mediapipe not installed — FaceLandmarker disabled")
            return

        model_path = MODEL_DIR / FACE_LANDMARKER_MODEL_FILENAME
        if not model_path.exists():
            if not self._download_model(
                model_path, FACE_LANDMARKER_MODEL_URL, "face landmarker"
            ):
                return
        # Verify integrity. Soft fail — EmotionService stays disabled
        # if the model is suspect, but the rest of the camera service
        # (presence, lux, zone/posture) is untouched.
        if not self._verify_model(
            model_path,
            FACE_LANDMARKER_MODEL_URL,
            EXPECTED_FACE_LANDMARKER_MODEL_MD5,
            "face landmarker",
        ):
            logger.warning(
                "FaceLandmarker model failed integrity check — emotion "
                "capture will stay disabled. mood_samples writes pause "
                "until the operator validates a new model and updates "
                "EXPECTED_FACE_LANDMARKER_MODEL_MD5."
            )
            return
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
            self._face_landmarker = FaceLandmarker.create_from_options(options)
            logger.info("FaceLandmarker initialized (emotion enabled)")
        except Exception as exc:
            logger.warning(
                "FaceLandmarker init failed — emotion will stay disabled: %s",
                exc,
            )
            self._face_landmarker = None

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

        # Open webcam (device 0 = built-in camera on Latitude). Bounded +
        # off-loop so a wedged V4L2 open can't freeze the backend or park
        # spawn_camera_service (which the watchdog awaits).
        try:
            self._cap = await self._open_capture_async()
            if self._cap is None:
                return
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

        # Verify model integrity against the pinned hash. Defends against
        # silent CDN regressions (Google republishes `latest/`) and
        # on-disk corruption. On mismatch, attempt ONE re-download in
        # case the local file rotted; if the fresh download also fails
        # to match, refuse to start — the camera lane stays cold and
        # /health flips to degraded so the operator notices.
        if not self._verify_model(
            face_model_path, MODEL_URL, EXPECTED_FACE_MODEL_MD5,
            "face detection",
        ):
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

        # Verify pose model integrity. Unlike face, this is a soft fail
        # — pose is a fallback for profile views, so a bad model means
        # "stay face-only" rather than "refuse to start the service."
        if pose_model_path is not None and not self._verify_model(
            pose_model_path, POSE_MODEL_URL, EXPECTED_POSE_MODEL_MD5, "pose",
        ):
            logger.warning(
                "Pose model failed integrity check — staying face-only. "
                "The Latitude's corner geometry means face-only loses "
                "profile-view detection, but the desktop pc_agent's "
                "presence stream still covers attendance vetoes."
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

    @staticmethod
    def _file_md5(path: Path) -> str:
        """Compute the hex MD5 digest of a file in fixed-size chunks.

        MD5 is fine here — this is an integrity check against
        accidental corruption + CDN regression, not a cryptographic
        defense. The model assets are public and small (~1 MB), so
        re-hashing on every camera start is cheap (<10ms).
        """
        h = hashlib.md5()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _verify_model(
        self,
        model_path: Path,
        url: str,
        expected_md5: str,
        label: str,
        *,
        re_download_ok: bool = True,
    ) -> bool:
        """Confirm a model file on disk matches its pinned hash; one
        self-healing re-download attempt on first mismatch.

        Returns True if the file is safe to load. Returns False (and
        logs a hard error) if the hash still mismatches after re-download
        — caller decides whether to refuse (face) or degrade gracefully
        (pose / face_landmarker). The ``HOME_HUB_SKIP_MODEL_HASH_CHECK``
        env var bypasses the gate for emergencies (e.g. operator
        validated a new model and is staging the constant update); it
        never silently flips on.

        Args:
            model_path: Filesystem path of the model file.
            url: CDN URL to fetch from on a re-download attempt.
            expected_md5: Pinned hex MD5 of the known-good bytes.
            label: Human-readable name for log messages
                ("face detection" / "pose" / "face landmarker").
            re_download_ok: If False, mismatch returns False immediately
                without attempting a re-download. Used when a previous
                re-download already failed (e.g. a same-boot retry from
                the watchdog).
        """

        if os.environ.get("HOME_HUB_SKIP_MODEL_HASH_CHECK") == "1":
            logger.warning(
                "Skipping %s model hash check (HOME_HUB_SKIP_MODEL_HASH_CHECK=1) — "
                "operator bypass; clear this env var once verification completes",
                label,
            )
            return True

        actual = self._file_md5(model_path)
        if actual == expected_md5:
            return True

        logger.warning(
            "%s model hash mismatch — expected=%s actual=%s. "
            "Attempting one re-download in case the local file is corrupt.",
            label.capitalize(), expected_md5, actual,
        )

        if not re_download_ok:
            return False

        if not self._download_model(model_path, url, label):
            logger.error(
                "%s model re-download failed; refusing to load to avoid "
                "running with an unverified model.", label.capitalize(),
            )
            return False

        actual_after = self._file_md5(model_path)
        if actual_after == expected_md5:
            logger.info("%s model hash restored after re-download", label.capitalize())
            return True

        logger.error(
            "%s model hash STILL mismatches after re-download "
            "(expected=%s, actual=%s). Either the CDN was updated or the local "
            "filesystem is unhealthy. Refusing to load. To unblock: verify the "
            "new model in shadow, then update the EXPECTED_*_MD5 constant in "
            "camera_service.py — or set HOME_HUB_SKIP_MODEL_HASH_CHECK=1 as a "
            "temporary bypass.",
            label.capitalize(), expected_md5, actual_after,
        )
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
            zone_sampled = config.get("zone_sampled")
            logger.info(
                "Applied lux calibration: exposure=%.2f, baseline_lux=%s, zone=%s",
                exposure,
                f"{self._baseline_lux:.1f}" if self._baseline_lux is not None else "unset",
                zone_sampled if zone_sampled is not None else "pre-roi",
            )
            if zone_sampled is None:
                # Persisted config predates the zone-weighted ROI metric. Live
                # readings are now sliced by zone but the baseline reflects a
                # full-frame mean — the multiplier will be biased until the
                # user re-runs POST /api/camera/calibrate while zone-committed.
                logger.warning(
                    "Pre-ROI calibration loaded — multiplier will be biased "
                    "until re-calibration. POST /api/camera/calibrate while "
                    "seated at the desk (or in bed) to capture a "
                    "zone-matched baseline."
                )
        except Exception as exc:
            logger.error("Failed to apply lux calibration: %s", exc, exc_info=True)

    async def calibrate_exposure(self) -> dict:
        """Binary-search webcam exposure until gray.mean() ≈ EXPOSURE_TARGET_LUX.

        Runs the blocking OpenCV loop in a thread pool. Persists the discovered
        exposure value to ``app_settings`` under ``lux_calibration_config`` so
        subsequent service restarts can re-apply it without re-calibrating.

        Requires a committed zone — baseline must reflect the same surface
        the live poll loop reads. With ``_last_zone == None`` we'd capture a
        full-frame baseline against zone-sliced live readings, structurally
        inflating the multiplier. Caller fix: sit at the desk (or in bed)
        for ~20s so zone commits, then re-trigger.

        Returns:
            ``{status, exposure_value, measured_lux, zone_sampled, detail}``.
        """
        if not self._enabled or self._cap is None or not self._cap.isOpened():
            return {"status": "error", "detail": "camera not available"}
        if self._paused:
            return {"status": "error", "detail": "camera paused (sleeping mode)"}
        if self._calibrating:
            return {"status": "error", "detail": "calibration already in progress"}
        if self._last_zone is None:
            return {
                "status": "error",
                "detail": (
                    "no committed zone — sit on the couch for ~20s so a zone "
                    "commits, then retry. Baseline must be captured at the "
                    "same ROI the live poll loop will read against."
                ),
            }

        self._calibrating = True
        zone_at_start = self._last_zone
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
                    "zone_sampled": zone_at_start,
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
                "Calibration complete: exposure=%.2f, baseline_lux=%.1f, zone=%s",
                result["exposure_value"],
                baseline,
                zone_at_start,
            )
            result["zone_sampled"] = zone_at_start
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
                    # Match poll-loop metric: sample the user's zone half
                    # so baseline reflects the same surface as live reads.
                    readings.append(_zone_weighted_lux(gray, self._last_zone))
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
        """Update exponential moving average of ambient lux.

        If the EMA is uninitialized OR hasn't been updated for longer than
        LUX_EMA_STALE_RESET_SECONDS (sleeping pause / all-day absence /
        watchdog reopen), snap to the raw reading instead of blending —
        otherwise the first post-resume frame averages yesterday's room
        light with today's, jerking the brightness multiplier.
        """
        now = datetime.now(timezone.utc)
        stale = (
            self._last_lux_update is None
            or (now - self._last_lux_update).total_seconds()
            >= LUX_EMA_STALE_RESET_SECONDS
        )
        if self._ema_lux is None or stale:
            self._ema_lux = raw_lux
        else:
            self._ema_lux = LUX_EMA_ALPHA * raw_lux + (1 - LUX_EMA_ALPHA) * self._ema_lux
        self._last_lux_update = now

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
        enough to trust — e.g. transit lighting waits ~4s of sustained
        absence before reacting to avoid blink-flickering.
        """
        return self._last_detection_at

    def is_present_within_seconds(self, seconds: int = 300) -> bool:
        """Coarse "is anyone home recently?" helper for non-zone-aware
        consumers (CelebrationOrchestrator, future TTS gating).

        Returns True iff:
            • The camera is disabled (we can't tell, so assume present —
              don't penalize TTS for an opt-out).
            • Last detection was "present" within the last ``seconds``.

        Returns False when:
            • Camera is enabled, last detection was "absent" or "unknown".
            • Camera is enabled, last "present" detection is older than
              the window (apartment empty long enough to dial volume back).
        """
        if not self._enabled:
            return True
        if self._last_detection != "present":
            return False
        if self._last_detection_at is None:
            return False
        age = (datetime.now(timezone.utc) - self._last_detection_at).total_seconds()
        return age <= seconds

    def _build_fusion_factors(
        self,
        status: str,
        detection_source: Optional[str],
        confidence: float,
        multiplier: float,
    ) -> list[dict]:
        """Build the camera lane's sub-factors for the analytics constellation.

        Returns up to five pips: presence (face/pose/absent), zone, posture,
        lux band, and a ``presence_sources`` attribution naming the live
        cameras. Uses currently-committed hysteresis values so pips don't
        flicker on single-frame misses. The presence_sources pip is appended
        in the poll loop where PresenceFusion is reachable; this method
        emits the first four.
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

        # Cap at 4 here — the optional presence_sources pip is appended
        # by the poll loop, which keeps PresenceFusion isolated to the one
        # call site that has access to the automation engine's wiring.
        return factors[:4]

    def set_heartbeat_registry(self, registry) -> None:
        """Inject the heartbeat registry (called from lifespan).

        The registry is used by the poll loop to publish liveness; the
        camera registers itself only on enable / resume and deregisters
        on disable / pause so legitimate downtime isn't flagged stale.
        """
        self._heartbeat = registry

    def _open_capture(self):
        """Open ``cv2.VideoCapture(0)`` with timeouts, resolution, and warm-up.

        Single home for the open dance: previously inlined at boot and on
        resume-from-sleeping; both sites now route through here. Sets V4L2
        read/open timeouts so a wedged kernel driver can be detected at the
        OpenCV layer (defense in depth on top of the asyncio watchdog), then
        discards one warm-up frame so the next ``_process_frame`` doesn't
        receive a corrupt first read post-reopen.

        Returns the opened ``cv2.VideoCapture`` or ``None`` on failure.
        """
        import cv2

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            logger.warning(
                "Camera service: webcam not available "
                "(may be in use by another process)"
            )
            return None

        # Property setters return False on backends that don't recognise the
        # property; that's fine — we still benefit on V4L2 where they apply.
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, CAP_OPEN_TIMEOUT_MS)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, CAP_READ_TIMEOUT_MS)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        try:
            cap.read()  # Warm-up read; first frame post-reopen is often junk.
        except Exception as exc:
            logger.warning("Warm-up frame read failed: %s", exc)
        return cap

    def _release_and_open(self, old: Optional[Any]) -> Optional[Any]:
        """Sync: release a prior handle (if any), then open a fresh one.

        Runs entirely in an executor thread (see ``_open_capture_async``)
        so that *both* the ``release()`` — which can block joining a V4L2
        worker thread parked in ``read()`` — and the open never run on the
        event loop. Release-before-open ordering matches the recovery path:
        a stranded handle is the exact failure that wedges ``/dev/video0``.
        """
        if old is not None:
            try:
                old.release()
            except Exception as exc:
                logger.warning("Camera release before reopen failed: %s", exc)
        return self._open_capture()

    async def _open_capture_async(self, *, release_first: Optional[Any] = None) -> Optional[Any]:
        """Open the capture off the event loop with a hard timeout.

        Every open path (boot ``start()``, sleeping resume, poll-loop reopen,
        watchdog recovery) routes through here so a wedged V4L2 open can
        neither freeze the loop nor park the caller. On timeout we log and
        return ``None``; the orphaned executor thread is left to exit when
        its syscall unblocks (or, if it never does, the watchdog's
        process-restart escalation reclaims the fd). ``release_first`` lets
        callers hand off a prior handle so the release also happens off-loop.
        """
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._release_and_open, release_first),
                timeout=CAP_OPEN_WATCHDOG_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Camera open exceeded %.0fs watchdog — treating as unavailable "
                "(V4L2 likely wedged; an executor thread may be parked on the "
                "open/read and holding /dev/video0 until the process restarts)",
                CAP_OPEN_WATCHDOG_SECONDS,
            )
            return None

    async def _recover_capture(self) -> None:
        """Release and reopen the capture handle from the asyncio thread.

        Called when the watchdog in ``poll_loop`` trips on a hung frame
        read. The orphaned executor thread is still parked inside
        ``cap.read()`` and holds ``self._cap_lock``; we deliberately do
        NOT take that lock here — OpenCV's ``release()`` is thread-safe
        at the C++ level and releasing under the orphan typically unblocks
        the V4L2 driver, letting the orphan exit cleanly on its next
        syscall. Release + reopen run off-loop with a hard timeout via
        ``_open_capture_async``. If reopen fails, ``self._cap`` stays
        ``None`` and ``_process_frame`` short-circuits at its top-of-function
        guard until a future iteration succeeds.
        """
        old = self._cap
        self._cap = None
        self._cap = await self._open_capture_async(release_first=old)
        if self._cap is None:
            logger.warning("Camera reopen during recovery failed; will retry next poll")
        else:
            logger.info("Camera capture recovered after watchdog timeout")

    async def poll_loop(self) -> None:
        """Background task — capture and classify one frame every POLL_INTERVAL seconds."""
        loop = asyncio.get_event_loop()

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)

                if not self._enabled or self._paused:
                    continue

                # Recover capture handle here rather than ticking heartbeat
                # first — otherwise the lane reads "fresh" while every frame
                # short-circuits at _process_frame's _cap=None guard. Hit on
                # 2026-05-17 after a sleeping→working resume with a still-
                # locked V4L2 handle.
                if self._cap is None:
                    self._cap = await self._open_capture_async()
                    if self._cap is None:
                        continue
                    logger.info("Camera capture reopened by poll loop")

                if self._heartbeat is not None:
                    self._heartbeat.tick("camera")

                # Run blocking frame capture + inference in thread pool.
                # Wrap in asyncio.wait_for so a hung V4L2 read can't park the
                # poll loop indefinitely (heartbeat, lux refresh, fusion lane
                # all stop ticking when this await never returns). On timeout
                # we release/reopen the capture handle and resume polling;
                # the orphan executor thread will exit when its read unblocks.
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, self._process_frame),
                        timeout=FRAME_READ_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Camera frame read exceeded %.1fs — releasing and "
                        "reopening capture",
                        FRAME_READ_TIMEOUT_S,
                    )
                    await self._recover_capture()
                    continue
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

                # Dispatch blendshapes to personality subscribers (Phase A).
                # Only when emotion is enabled, a face was detected with
                # reasonable confidence, and the frame actually returned a
                # blendshape map. Async callbacks are awaited inline — they
                # are required to be fast (cache + return); slow work goes
                # in their own poll loops.
                blendshapes = result.get("blendshapes")
                if (
                    self._emotion_enabled
                    and blendshapes
                    and source == "face"
                    and confidence >= FACE_LANDMARKER_TRIGGER_CONFIDENCE
                    and self._blendshape_callbacks
                ):
                    bs_ts = self._last_detection_at
                    for cb in list(self._blendshape_callbacks):
                        try:
                            res = cb(blendshapes, confidence, bs_ts)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            logger.exception(
                                "blendshape callback raised — ignoring"
                            )
                # Run zone + posture hysteresis — may commit new committed values.
                # `present_observed` lets the hysteresis distinguish "user
                # absent this frame" (don't refresh stale commits) from
                # "user observed but candidate uncertain" (weak face / strong
                # face without pose — prior commit still valid, refresh
                # freshness so the lighting overlay honors it).
                present_observed = status == "present"
                zone_before = self._last_zone
                posture_before = self._last_posture
                self._apply_zone_hysteresis(
                    frame_zone, present_observed=present_observed,
                )
                self._apply_posture_hysteresis(
                    frame_posture, present_observed=present_observed,
                )
                await self._maybe_notify_camera_commit(
                    zone_before=zone_before,
                    posture_before=posture_before,
                )

                # Fan out the just-settled state to PresenceFusion (or any
                # tagged-source consumer registered via
                # register_observation_callback). Done after hysteresis so
                # the reading carries committed zone/posture, not candidates.
                # Sync-only callbacks; intentionally simple — fusion's
                # on_observation is just a dict assignment.
                if self._observation_callbacks:
                    try:
                        from backend.services.presence_fusion import (
                            PresenceReading,
                        )
                        reading = PresenceReading(
                            source="latitude",
                            captured_at=self._last_detection_at
                            or datetime.now(timezone.utc),
                            face_present=(status == "present"),
                            face_confidence=confidence,
                            detection_source=source,
                            zone=self._last_zone,
                            posture=self._last_posture,
                            pose_visible_landmarks=pose_landmark_count or None,
                        )
                        for cb in list(self._observation_callbacks):
                            try:
                                cb(reading)
                            except Exception:
                                logger.exception(
                                    "observation callback raised — ignoring"
                                )
                    except Exception:
                        logger.exception(
                            "failed to dispatch presence observation"
                        )

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

                # Append the multi-source attribution factor (Commit 3 of the
                # multi-camera fusion plan). PresenceFusion.as_fusion_factor()
                # returns None when no source has reported recently — in that
                # case we leave camera_factors as-is so we don't emit a
                # confusing "presence_sources: (empty)" pip.
                presence_fusion = getattr(
                    self._automation, "_presence_fusion", None,
                )
                if presence_fusion is not None:
                    presence_factor = presence_fusion.as_fusion_factor()
                    if presence_factor is not None:
                        camera_factors.append(presence_factor)

                # Keep the camera lane fresh in confidence fusion every cycle.
                # The edge-triggered report_activity() calls below drive actual
                # mode changes; this keeps fusion's signal alive while the user
                # sits steadily and no transition fires.
                fusion = getattr(self._automation, "_confidence_fusion", None)
                if fusion and status in ("present", "absent"):
                    fusion.report_signal(
                        "camera", "idle", confidence, factors=camera_factors,
                    )

                if status == "present":
                    was_absent = self._consecutive_absent >= ABSENT_THRESHOLD
                    self._consecutive_absent = 0

                    # If we were absent for long enough, report idle (return).
                    if was_absent or self._was_absent:
                        self._was_absent = False
                        await self._automation.report_activity(
                            mode="idle", source="camera", factors=camera_factors,
                        )
                        # Also clear the external-off suppression flag if it's
                        # set. report_activity above does NOT clear the flag
                        # for mode=idle reports, so without this call the
                        # engine stays suppressed indefinitely when the Hue
                        # iOS app's "Leaving home" automation turned lights
                        # off and the user returns without touching the PC.
                        # No-op when the flag is already clear (idempotent).
                        signal_presence = getattr(
                            self._automation, "signal_presence", None,
                        )
                        if signal_presence is not None:
                            await signal_presence("camera")
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
                        # User has been gone long enough that any committed
                        # zone/posture is now stale by definition, since we
                        # have no idea where they'll re-enter from. Clearing
                        # here prevents the bed+reclined overlay from firing
                        # on values committed hours (or a sleep cycle) ago.
                        self._clear_committed_zone_posture("absent threshold")
                        await self._automation.report_activity(
                            mode="idle", source="camera", factors=camera_factors,
                        )
                        logger.info(
                            "No person detected for %ds — reported idle",
                            ABSENT_THRESHOLD * POLL_INTERVAL,
                        )

                # Log ML decision
                if self._ml_logger and status in ("present", "absent"):
                    mode = "idle"
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

    def _apply_zone_hysteresis(
        self,
        candidate: Optional[str],
        *,
        present_observed: bool = False,
    ) -> None:
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
            # Weak-face frames (and strong-face-without-pose) emit candidate=None
            # to prevent chair-back false positives from flipping the zone. When
            # the camera still observes a person (status=present), the prior
            # commit is semantically current — refresh the freshness timestamp
            # so the lighting overlay keeps honoring it. Brief-absence frames
            # (status=absent → present_observed=False) preserve but don't
            # refresh, so a user who left for the night still goes stale.
            if present_observed and self._last_zone is not None:
                self._last_zone_at = now
            return

        if candidate == self._last_zone:
            # Steady-state confirmation: refresh the commit timestamp so
            # downstream freshness gates (ZONE_POSTURE_FRESHNESS_SECONDS in
            # the lighting overlay) see a live reading. Without this refresh,
            # `_last_zone_at` only updates on zone TRANSITIONS, so a user who
            # has been in the same zone for >5 min appears "stale" to the
            # overlay and Branch 3 (bed-zone dim) silently disengages.
            self._last_zone_at = now
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

    def _apply_posture_hysteresis(
        self,
        candidate: Optional[str],
        *,
        present_observed: bool = False,
    ) -> None:
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

        # Posture has no consumer since the 2026-05-27 living-room move (the
        # bed-zone overlays + zone_posture_rule that read it are dormant). At
        # the desk it was always noise (the desk occludes hips → MediaPipe
        # places the landmark at chest level → false reclined); on the couch
        # it's simply unconsumed. Suppress for both Latitude zones so we don't
        # publish a meaningless reclined/upright over status + WebSocket.
        if self._last_zone in (ZONE_DESK, ZONE_COUCH):
            if self._last_posture is not None or self._candidate_posture is not None:
                self._last_posture = None
                self._last_posture_at = None
                self._candidate_posture = None
                self._candidate_posture_since = None
            return

        if candidate is None:
            # Face path can't classify posture (no torso landmarks). When the
            # camera observes a person but pose didn't fire this frame, the
            # prior posture commit is still semantically current — refresh
            # the freshness timestamp. Without this, dim-room sessions where
            # pose fires only ~1-in-10 polls let posture freshness expire
            # while the user is still reclined in bed.
            if present_observed and self._last_posture is not None:
                self._last_posture_at = now
            return

        if candidate == self._last_posture:
            # Steady-state confirmation: refresh the commit timestamp so
            # downstream freshness gates see a live reading. Mirrors the
            # zone hysteresis fix; without it, posture goes "stale" to the
            # lighting overlay even though the camera is still observing
            # the same posture every frame.
            self._last_posture_at = now
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

    async def _maybe_notify_camera_commit(
        self,
        *,
        zone_before: Optional[str],
        posture_before: Optional[str],
    ) -> None:
        """Nudge the engine to re-apply lights when zone or posture commits.

        Called once per poll, after both hysteresis methods have run.
        Compares pre-hysteresis state to post-hysteresis state and only
        fires when a value transitioned to a new non-None commit
        (None → "bed", "desk" → "bed", None → "reclined", etc.). Skips:

        - Steady-state refreshes (value unchanged) — those touched the
          ``_committed_at`` timestamp only; the overlay's output is
          identical so a re-apply would just be wasted writes.
        - Clears (commit → None) — overlay no-ops on missing values.
        - First-frame initialization where both before and after are None.

        Why this exists: ``_apply_mode`` only runs on mode transitions,
        and ``run_loop``'s 60s periodic re-apply skips entirely when a
        manual override is active. Without this hook, a zone/posture
        commit landing AFTER lights have already settled (common
        post-restart, when hysteresis takes 60-120s) would leave the
        lights at the no-overlay baseline until the next mode change.
        """
        zone_committed = (
            self._last_zone is not None
            and self._last_zone != zone_before
        )
        posture_committed = (
            self._last_posture is not None
            and self._last_posture != posture_before
        )
        if not (zone_committed or posture_committed):
            return
        if self._automation is None:
            return
        notify = getattr(self._automation, "notify_camera_commit", None)
        if notify is None:
            return
        try:
            await notify()
        except Exception:
            logger.exception(
                "notify_camera_commit failed (zone_committed=%s, "
                "posture_committed=%s)",
                zone_committed, posture_committed,
            )

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

        def _mean_y(
            indices: tuple[int, ...],
            min_vis: float = MIN_POSE_VISIBILITY,
        ) -> Optional[float]:
            ys = [
                float(landmarks[i].y) for i in indices
                if i < len(landmarks)
                and float(getattr(landmarks[i], "visibility", 0.0)) >= min_vis
            ]
            return sum(ys) / len(ys) if ys else None

        shoulder_y = _mean_y((POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER))
        hip_y = _mean_y(
            (POSE_LEFT_HIP, POSE_RIGHT_HIP),
            min_vis=MIN_POSE_VISIBILITY_HIP,
        )
        if shoulder_y is None or hip_y is None:
            return None
        delta = hip_y - shoulder_y
        if delta < POSTURE_MIN_ANATOMICAL_DELTA:
            return None
        return POSTURE_UPRIGHT if delta >= POSTURE_UPRIGHT_MIN_DELTA else POSTURE_RECLINED

    def _process_frame(self) -> Optional[dict]:
        """Capture a frame, run both face detection and pose landmarker,
        arbitrate via face-confidence threshold, compute ambient lux.

        Runs in a thread pool executor. Frames never leave this method —
        they are overwritten and dereferenced before returning.

        Selection (in order):
          1. Face strong (conf ≥ FACE_TRUST_THRESHOLD) → face wins outright;
             if pose also present, borrow its posture as a free upgrade.
          2. Pose present (≥3 torso landmarks at ≥MIN_POSE_VISIBILITY) → pose
             wins. Rescues the chair-back-vs-real-face ambiguous case where
             two face detections trade `max(score)` frame-to-frame.
          3. Weak face only (no pose) → presence accepted but zone=None and
             posture=None. We don't trust low-confidence face detections to
             drive zone changes — chair-back / picture-frame silhouettes
             regularly clear MIN_FACE_CONFIDENCE. Hysteresis preserves the
             last pose-committed zone through dim periods.
          4. Else → absent.

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

            # Compute ambient light level from the zone-matching half of
            # the frame. Full-frame mean was biased by the brighter bed
            # side when the user was at the desk (and vice versa).
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ambient_lux = _zone_weighted_lux(gray, self._last_zone)

            # Convert to RGB for MediaPipe (reused across both detectors)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            # Face detection (~15ms at 640×480)
            face_best = None
            face_conf = 0.0
            face_zone = None
            face_results = self._face_detector.detect(mp_image)
            if face_results.detections:
                face_best = max(
                    face_results.detections,
                    key=lambda d: d.categories[0].score,
                )
                face_conf = float(face_best.categories[0].score)
                # Living-room camera frames a single area — the couch. The old
                # desk/bed center-X split was bedroom geometry (see ZONE_COUCH).
                face_zone = ZONE_COUCH

            # Face-anchor refresh. Any face above FACE_ANCHOR_MIN_CONFIDENCE
            # refreshes its zone's anchor. The TTL is checked downstream when
            # arbitrating pose-only present commits.
            if (
                face_best is not None
                and face_conf >= FACE_ANCHOR_MIN_CONFIDENCE
                and face_zone is not None
            ):
                self._face_anchor_at[face_zone] = datetime.now(timezone.utc)

            # Face Landmarker (emotion only — ~20ms, ~3MB model). Conditional
            # on emotion_enabled AND a face already detected above with
            # sufficient confidence; otherwise we'd burn the budget producing
            # garbage blendshapes on furniture silhouettes.
            blendshapes: Optional[dict[str, float]] = None
            if (
                self._emotion_enabled
                and self._face_landmarker is not None
                and face_best is not None
                and face_conf >= FACE_LANDMARKER_TRIGGER_CONFIDENCE
            ):
                try:
                    fl_result = self._face_landmarker.detect(mp_image)
                    if fl_result.face_blendshapes:
                        blendshapes = {
                            cat.category_name: float(cat.score)
                            for cat in fl_result.face_blendshapes[0]
                        }
                except Exception:
                    logger.debug("FaceLandmarker.detect failed", exc_info=True)

            # Pose landmarker (~60ms at 640×480) — runs every frame so it can
            # arbitrate when face is unreliable. Total per-frame cost ~75ms,
            # well under the 2s poll budget.
            pose_present = False
            pose_mean_vis = 0.0
            pose_count = 0
            pose_zone = None
            pose_posture = None
            pose_result = None
            if self._pose_landmarker is not None:
                pose_result = self._pose_landmarker.detect(mp_image)
                pose_present, pose_mean_vis, pose_count = self._evaluate_pose(
                    pose_result
                )
                if pose_present:
                    # Single living-room zone — see ZONE_COUCH. The old
                    # shoulder-center-X split was bedroom desk/bed geometry.
                    pose_zone = ZONE_COUCH
                    pose_posture = self._evaluate_posture(pose_result)

            # Selection — face wins outright above the trust threshold,
            # otherwise pose-strong overrules a weak face read.
            if face_best is not None and face_conf >= FACE_TRUST_THRESHOLD:
                return {
                    "status": "present",
                    "confidence": face_conf,
                    "source": "face",
                    "pose_landmark_count": pose_count,
                    "ambient_lux": ambient_lux,
                    "zone": face_zone,
                    # Borrow pose's posture as a free upgrade when available.
                    "posture": pose_posture if pose_present else None,
                    "blendshapes": blendshapes,
                }

            if pose_present:
                # Face-anchor gate. Pose alone (no co-temporal strong face)
                # cannot distinguish a real user from the empty office chair
                # — chair's torso-symmetric silhouette fires pose at 0.98
                # with all 5 landmarks (2026-05-21 truth-table). Require a
                # recent face anchor before honoring this commit.
                #
                # When pose_zone is None (both shoulders below visibility
                # floor — deep profile, bent forward), fall back to the
                # most-recent anchor in ANY zone. The zone ambiguity is
                # about localization, not presence — a face seen anywhere
                # recently is evidence of a real person who's now reoriented.
                if pose_zone:
                    anchor_at = self._face_anchor_at.get(pose_zone)
                else:
                    anchor_at = (
                        max(self._face_anchor_at.values())
                        if self._face_anchor_at else None
                    )
                anchor_age = (
                    (datetime.now(timezone.utc) - anchor_at).total_seconds()
                    if anchor_at is not None
                    else None
                )
                anchor_fresh = (
                    anchor_age is not None and anchor_age <= FACE_ANCHOR_TTL_SECONDS
                )
                if anchor_fresh:
                    return {
                        "status": "present",
                        "confidence": pose_mean_vis,
                        "source": "pose",
                        "pose_landmark_count": pose_count,
                        "ambient_lux": ambient_lux,
                        "zone": pose_zone,
                        "posture": pose_posture,
                        "blendshapes": blendshapes,
                    }
                # Stale anchor — pose silhouette is more likely furniture
                # than the user. Fall through to weak-face / absent paths.
                # The face fallback below would also need anchor support if
                # face_best is weak; we keep the existing low-lux floor as
                # the second line of defense.

            if face_best is not None:
                # Weak face + no pose. We trust the detection for *presence*
                # but not for *zone disambiguation*: face-like silhouettes
                # (high-back office chair, picture frames) regularly clear
                # MIN_FACE_CONFIDENCE under low light. Emit zone=None so
                # the hysteresis layer preserves whatever pose last
                # committed — prevents the bed-overlay-dims-room → pose-
                # blinded → chair-back-wins-face → zone-flips-to-desk loop
                # observed 2026-05-05.
                #
                # Low-lux gate: at ema_lux < LOW_LUX_THRESHOLD the chair-back
                # ghosts hover in the 0.15–0.25 band and re-flip downstream
                # absent dwells. Demand a tighter confidence floor when the
                # room is dim so a true exit produces clean sustained
                # absence (TransitLightingService / DeskExitKitchenService
                # both depend on this). Strong face and pose paths above
                # already returned, so we only short-circuit the weak path.
                if (
                    self._ema_lux is not None
                    and self._ema_lux < LOW_LUX_THRESHOLD
                    and face_conf < LOW_LUX_FACE_FLOOR_CONF
                ):
                    return {
                        "status": "absent",
                        "confidence": 0.0,
                        "source": None,
                        "pose_landmark_count": 0,
                        "ambient_lux": ambient_lux,
                        "zone": None,
                        "posture": None,
                        "blendshapes": None,
                    }
                return {
                    "status": "present",
                    "confidence": face_conf,
                    "source": "face",
                    "pose_landmark_count": 0,
                    "ambient_lux": ambient_lux,
                    "zone": None,
                    "posture": None,  # Face path can't derive torso geometry
                    "blendshapes": blendshapes,
                }

            return {
                "status": "absent",
                "confidence": 0.0,
                "source": None,
                "pose_landmark_count": 0,
                "ambient_lux": ambient_lux,
                "zone": None,
                "posture": None,
                "blendshapes": None,
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
                # Release camera so the LED turns off. Hand the handle off to
                # an executor (bounded) and null _cap first: release() can
                # block joining a V4L2 worker thread parked in read(), which
                # would otherwise freeze the event loop on the mode flip.
                old = self._cap
                self._cap = None
                if old is not None:
                    try:
                        await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(None, old.release),
                            timeout=CAP_OPEN_WATCHDOG_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Camera release on sleep exceeded %.0fs watchdog — "
                            "LED/handle may linger until the process restarts",
                            CAP_OPEN_WATCHDOG_SECONDS,
                        )
                    except Exception as exc:
                        logger.warning("Camera release on sleep failed: %s", exc)
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
                # Reopen camera — release any stranded handle first, off-loop +
                # bounded, matching the recovery path. A handle left over from
                # a failed sleep-entry release is exactly what wedges
                # /dev/video0 across the sleep cycle.
                old = self._cap
                self._cap = None
                self._cap = await self._open_capture_async(release_first=old)
                if self._cap is not None:
                    logger.info("Camera resumed after sleeping mode")
                else:
                    logger.warning("Camera unavailable after sleep — will retry next poll")

    async def close(self) -> None:
        """Release camera and MediaPipe resources.

        Idempotent: safe to call on a half-dead service. Cancels the
        poll_loop task if we own a handle to it so a respawn doesn't
        race with the old loop's next iteration.
        """
        self._enabled = False
        if self._heartbeat is not None:
            self._heartbeat.deregister("camera")
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                # CancelledError is the expected outcome; any other
                # exception was already logged inside poll_loop's
                # top-level except block, so we just swallow here.
                pass
        self._poll_task = None
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
        now = datetime.now(timezone.utc)
        face_anchor_age_s = {
            zone: (now - ts).total_seconds()
            for zone, ts in self._face_anchor_at.items()
        }
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
            "face_anchor_age_s_by_zone": face_anchor_age_s,
            "face_anchor_ttl_s": FACE_ANCHOR_TTL_SECONDS,
        }


# ----------------------------------------------------------------------
# Module-level helpers — spawn + watchdog
# ----------------------------------------------------------------------

# How stale the camera heartbeat must be before the watchdog respawns
# the service. Set well above 2x POLL_INTERVAL (the /health staleness
# threshold) so we only step in for genuine wedges, not transient slow
# frames. Picked at 60s — the V4L2-wedge incident on 2026-05-20 ran for
# 12h before manual intervention. End-to-end detection latency is
# bounded by CAMERA_WATCHDOG_INTERVAL_SECONDS + CAMERA_WATCHDOG_STALE_SECONDS
# (worst case: heartbeat just went stale right after the previous tick).
CAMERA_WATCHDOG_STALE_SECONDS = 60.0

# How often the watchdog re-evaluates. 5 minutes balances "fast enough
# to recover the lane during a single working session" with "infrequent
# enough that a flapping V4L2 doesn't churn." A respawn itself takes
# ~3–5s (model download is cached after first boot).
CAMERA_WATCHDOG_INTERVAL_SECONDS = 300.0

# When an orphaned cv2/V4L2 worker thread parks holding /dev/video0, the
# fd is leaked *inside this process* — in-process respawn can never reclaim
# it (release() from another thread doesn't free a parked fd). The only
# reliable reclaim is a fresh process, which systemd (Restart=always) gives
# us on exit. After this many consecutive watchdog respawns fail to bring
# the lane back, escalate to a process restart. 3 ≈ 15 min of in-process
# attempts before the heavier hammer — both the 2026-05-20 (12h) and
# 2026-05-27 (7.8h) wedges needed a manual restart that this automates.
CAMERA_WEDGE_RESTART_THRESHOLD = 3

# Hard ceiling on the bounded spawn await inside the watchdog. A spawn that
# exceeds this is treated as a failed respawn (counts toward escalation) so
# a hung start() can never silence the supervisor again (root cause of the
# 2026-05-27 watchdog going dark for ~4h). Generous over start()'s normal
# ~3–5s and over CAP_OPEN_WATCHDOG_SECONDS so an honest slow boot isn't cut off.
CAMERA_SPAWN_WATCHDOG_SECONDS = 30.0

# Don't let the process-restart escalation become a boot loop if the camera
# is wedged at the hardware level (a fresh process would re-wedge and re-exit).
# Persist the last escalation time and refuse another within this window.
CAMERA_WEDGE_RESTART_COOLDOWN_SECONDS = 3600.0


async def spawn_camera_service(app: "FastAPI", *, reason: str) -> dict:
    """Spawn a fresh CameraService on ``app.state``, replacing any stale
    instance.

    Shared by ``POST /api/camera/enable`` and ``camera_watchdog_loop``.
    Releases the V4L2 handle held by a half-dead predecessor before
    instantiating the replacement, so a stuck ``/dev/video0`` doesn't
    keep failing acquisitions forever. The return shape matches the
    route's response contract so the toggle handler can pass it through.

    Wiring mirrors ``bootstrap.py``'s camera-startup block — keep these
    in sync (subscribers: automation engine, event_logger, ambient_sound,
    presence fusion, mode-change dispatch).

    Args:
        app: The FastAPI app whose ``app.state`` holds the wiring.
        reason: Short tag for logs/notifications (``"api_toggle"``,
            ``"watchdog_stale_heartbeat"``, ``"watchdog_dead_service"``).
    """
    automation = app.state.automation

    stale = getattr(app.state, "camera_service", None)
    if stale is not None:
        logger.info(
            "Releasing previous camera service before respawn (reason=%s, "
            "stale_enabled=%s)",
            reason, getattr(stale, "enabled", None),
        )
        # Drop the dead instance's mode-change subscription BEFORE
        # closing. Otherwise the appended callback list keeps growing
        # one entry per respawn, and dead-instance callbacks can race a
        # new instance for the V4L2 handle on the next mode flip
        # (sleeping→working would call _open_capture on the closed
        # service, reopening a handle nothing tracks).
        automation.deregister_on_mode_change(stale.on_mode_change)
        try:
            await stale.close()
        except Exception:
            logger.exception("Previous camera close() raised — continuing")
        app.state.camera_service = None

    ws_manager = app.state.ws_manager
    ml_logger = getattr(app.state, "ml_logger", None)
    heartbeats = getattr(app.state, "heartbeats", None)

    camera = CameraService(ws_manager, automation, ml_logger)
    if heartbeats is not None:
        camera.set_heartbeat_registry(heartbeats)

    await camera.start()

    if not camera.enabled:
        try:
            await camera.close()
        except Exception:
            logger.exception("Cleanup close() raised after failed start — continuing")
        return {
            "status": "error",
            "detail": "Camera unavailable (may be in use or missing)",
        }

    app.state.camera_service = camera
    automation.register_on_mode_change(camera.on_mode_change)
    automation.set_camera_service(camera)
    # Re-wire the rest of the subscriber set so a respawn restores all
    # context (zone enrichment on activity_events rows, presence-aware
    # ambient volume policy) — not just the mode-change dispatch.
    for attr in ("event_logger", "ambient_sound", "celebration_orchestrator"):
        subscriber = getattr(app.state, attr, None)
        if subscriber is not None and hasattr(subscriber, "set_camera_service"):
            subscriber.set_camera_service(camera)
    presence = getattr(app.state, "presence", None)
    if presence is not None:
        camera.register_observation_callback(presence.on_observation)
    # Stamp the poll task on the service so close() / next respawn can
    # cancel + await it. Without this, a respawn races the old task.
    camera._poll_task = asyncio.create_task(camera.poll_loop())
    logger.info("Camera service started (reason=%s)", reason)
    return {"status": "ok", "detail": "Camera enabled", **camera.get_status()}


def _camera_heartbeat_age(heartbeats: Any) -> Optional[float]:
    """Return the age (seconds) of the ``camera`` heartbeat, or ``None``
    if it's not registered. ``heartbeats`` is a ``HeartbeatRegistry``
    (annotated as ``Any`` to avoid a hard import dependency here)."""
    if heartbeats is None:
        return None
    snapshot = heartbeats.snapshot()
    for row in snapshot:
        if row["name"] == "camera":
            return float(row["age_seconds"])
    return None


async def _escalate_camera_wedge_restart(app: "FastAPI", detail: str) -> bool:
    """Last-resort recovery: exit so systemd (Restart=always) brings the
    unit back on a clean ``/dev/video0`` fd.

    When an orphaned cv2/V4L2 worker thread parks holding the device, the
    fd is leaked *inside this process* — ``spawn_camera_service``'s
    ``release()`` from another thread can't reclaim it, so in-process
    respawn fails forever (the 2026-05-20 + 2026-05-27 incidents). Only a
    fresh process frees it. Rate-limited via the ``camera_wedge_last_restart``
    app_setting so a hardware-level wedge — where a fresh process would
    immediately re-wedge — can't become a boot loop.

    Returns ``False`` (logs, does nothing else) when inside the cooldown
    window. Otherwise it signals shutdown and does not meaningfully return —
    the process is going down.
    """
    from backend.api.routes.routines import load_setting, save_setting

    now = datetime.now(timezone.utc)
    try:
        stamp = await load_setting("camera_wedge_last_restart")
        last_iso = (stamp or {}).get("at")
        if last_iso:
            elapsed = (now - datetime.fromisoformat(last_iso)).total_seconds()
            if elapsed < CAMERA_WEDGE_RESTART_COOLDOWN_SECONDS:
                logger.error(
                    "Camera wedge persists (%s) but a process-restart escalation "
                    "fired %.0fs ago (<%.0fs cooldown) — NOT restarting. Likely a "
                    "hardware-level V4L2 wedge needing manual intervention.",
                    detail, elapsed, CAMERA_WEDGE_RESTART_COOLDOWN_SECONDS,
                )
                return False
    except Exception:
        logger.exception("Camera wedge cooldown check failed — proceeding with restart")

    try:
        await save_setting(
            "camera_wedge_last_restart", {"at": now.isoformat(), "detail": detail}
        )
    except Exception:
        logger.exception("Failed to persist camera wedge restart stamp — continuing")

    logger.critical(
        "Camera wedge unrecoverable in-process after %d respawns (%s) — restarting "
        "the service so systemd reclaims /dev/video0",
        CAMERA_WEDGE_RESTART_THRESHOLD, detail,
    )
    ws_manager = getattr(app.state, "ws_manager", None)
    if ws_manager is not None:
        try:
            await ws_manager.broadcast(
                "notification",
                {
                    "kind": "system",
                    "title": "Camera wedged — restarting service",
                    "subtitle": "V4L2 handle stuck; recovering via process restart",
                    "source": "camera_watchdog",
                },
            )
        except Exception:
            logger.exception("Camera wedge: restart notification broadcast failed")

    # Let the WS frame + logs flush before we go down.
    await asyncio.sleep(1.0)

    # SIGTERM lets the lifespan shutdown run cleanly; systemd Restart=always
    # brings the unit back. os._exit is the hard backstop only if the signal
    # itself can't be delivered — a fresh process is the whole point.
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        logger.exception("SIGTERM self-signal failed — hard-exiting")
        os._exit(1)
    return True


async def camera_watchdog_loop(app: "FastAPI") -> None:
    """Background supervisor — respawn the camera service when it goes
    silent.

    Three trigger conditions, in priority order:

    1. ``camera_enabled=True`` in app_settings but ``app.state.camera_service``
       is ``None`` (boot start failed; route start failed; user
       re-enabled but the in-flight start hit an error).
    2. The service exists but its ``_enabled`` flag is False (poll_loop
       crashed without close() running — shouldn't happen with the
       current top-level except guard, but defense in depth).
    3. The service is enabled but the heartbeat is stale beyond
       ``CAMERA_WATCHDOG_STALE_SECONDS`` (the documented failure mode:
       V4L2 wedged after suspend/resume, ``_cap=None`` and the comment
       at poll_loop's reopen block deliberately gates heartbeat ticks
       on capture acquisition, so a wedged camera reads as a stale loop).

    Skips the ``_paused`` case (sleeping mode legitimately deregisters
    the heartbeat) and the camera-disabled case (no work to do).

    Emits a ``notification`` WebSocket event on each respawn so the
    desktop toast surface logs the recovery — gives the user a paper
    trail without needing to read journalctl.

    The spawn is bounded by ``CAMERA_SPAWN_WATCHDOG_SECONDS`` so a hung
    start() can't silence the supervisor. After
    ``CAMERA_WEDGE_RESTART_THRESHOLD`` consecutive failed respawns the loop
    escalates to a process restart (``_escalate_camera_wedge_restart``) —
    the only way to reclaim an orphaned, intra-process ``/dev/video0`` fd.
    """
    from backend.api.routes.routines import load_setting

    logger.info(
        "Camera watchdog started (interval=%.0fs, stale_threshold=%.0fs)",
        CAMERA_WATCHDOG_INTERVAL_SECONDS, CAMERA_WATCHDOG_STALE_SECONDS,
    )

    # Consecutive respawns that failed to bring the lane back. In-process
    # respawn can't reclaim an orphaned V4L2 fd, so after
    # CAMERA_WEDGE_RESTART_THRESHOLD failures we escalate to a process restart.
    consecutive_respawn_failures = 0

    while True:
        try:
            await asyncio.sleep(CAMERA_WATCHDOG_INTERVAL_SECONDS)

            setting = await load_setting("camera_enabled")
            if not setting or not setting.get("enabled", False):
                continue

            # Sleeping-mode privacy gate. The whole point of sleeping
            # mode is that the camera is off — LED dark, no captures.
            # The watchdog must NEVER respawn the service during this
            # window, even if the service is dead / None / heartbeat
            # stale, because doing so turns the LED on while the user
            # is asleep. This check intentionally fires BEFORE the
            # three respawn triggers (was previously only the
            # _paused-on-existing-service case that skipped). Recovery
            # for a service that died during sleep happens naturally:
            # on_mode_change leaving sleeping does the right thing if
            # the service is still live, and the next watchdog tick
            # after waking respawns it if it isn't.
            automation = getattr(app.state, "automation", None)
            if automation is not None and automation.current_mode == "sleeping":
                continue

            service = getattr(app.state, "camera_service", None)
            heartbeats = getattr(app.state, "heartbeats", None)

            reason: Optional[str] = None
            detail: str = ""
            if service is None:
                reason = "watchdog_no_service"
                detail = "camera_enabled is true but no service instance is live"
            elif not service.enabled:
                reason = "watchdog_dead_service"
                detail = "service instance present but _enabled=False"
            elif getattr(service, "_paused", False):
                # Defense in depth: an existing service can also be
                # _paused for reasons unrelated to sleeping mode (future
                # callers might add a "Do Not Disturb" or "vacation"
                # pause). The current_mode gate above handles the
                # sleeping case; this catches any other legitimate pause.
                continue
            else:
                age = _camera_heartbeat_age(heartbeats)
                if age is not None and age > CAMERA_WATCHDOG_STALE_SECONDS:
                    reason = "watchdog_stale_heartbeat"
                    detail = f"camera heartbeat stale ({age:.0f}s)"

            if reason is None:
                continue

            logger.warning(
                "Camera watchdog: %s — respawning service (%s)",
                reason, detail,
            )

            # Bound the spawn: a hung start() (V4L2 open parked) must not be
            # able to silence the supervisor — that's exactly how the watchdog
            # went dark for ~4h on 2026-05-27. A timeout counts as a failed
            # respawn so it feeds the escalation.
            try:
                result = await asyncio.wait_for(
                    spawn_camera_service(app, reason=reason),
                    timeout=CAMERA_SPAWN_WATCHDOG_SECONDS,
                )
            except asyncio.TimeoutError:
                result = {"status": "error", "detail": "spawn exceeded watchdog timeout"}
                logger.warning(
                    "Camera watchdog: spawn exceeded %.0fs — counting as failed respawn",
                    CAMERA_SPAWN_WATCHDOG_SECONDS,
                )

            respawn_ok = result.get("status") == "ok"
            if respawn_ok:
                consecutive_respawn_failures = 0
            else:
                consecutive_respawn_failures += 1

            ws_manager = getattr(app.state, "ws_manager", None)
            if ws_manager is not None:
                try:
                    await ws_manager.broadcast(
                        "notification",
                        {
                            "kind": "system",
                            "title": "Camera recovered"
                                if respawn_ok
                                else "Camera recovery failed",
                            "subtitle": detail,
                            "source": "camera_watchdog",
                        },
                    )
                except Exception:
                    logger.exception(
                        "Camera watchdog: failed to broadcast notification"
                    )

            # In-process respawn cannot reclaim an orphaned /dev/video0 fd.
            # After repeated failures, escalate to a process restart (systemd
            # reclaims the device on a clean boot).
            if consecutive_respawn_failures >= CAMERA_WEDGE_RESTART_THRESHOLD:
                escalation_detail = (
                    f"{consecutive_respawn_failures} consecutive failed respawns; "
                    f"last reason={reason} ({detail})"
                )
                # Reset regardless of outcome: on a successful escalation the
                # process is going down; on a cooldown-blocked one we re-arm the
                # in-process attempts rather than re-logging the block every tick.
                consecutive_respawn_failures = 0
                await _escalate_camera_wedge_restart(app, escalation_detail)

        except asyncio.CancelledError:
            logger.info("Camera watchdog stopped")
            raise
        except Exception:
            logger.exception("Camera watchdog iteration failed — continuing")
            # Brief back-off after an exception so we don't tight-loop on
            # a persistent error. Still much faster than the normal
            # interval so we recover quickly once the underlying issue
            # clears.
            await asyncio.sleep(30.0)
