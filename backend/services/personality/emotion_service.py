"""EmotionService — face blendshapes → continuous mood vector.

Reads MediaPipe FaceLandmarker blendshapes published by camera_service
(opt-in: emotion_enabled setting, separate from camera_enabled), maps
the 52 ARKit-style values to a (valence, arousal, focus) triple via a
hand-tuned linear coefficient table, EMA-smooths the result, and
persists one row per ``PERSIST_INTERVAL_S`` to ``mood_samples``.

Phase A: SHADOW-LOG ONLY. No actuation. The mood vector is exposed via
``get_current()`` for the calibration UI and the future Mood-Ring light
(Phase B). No fusion-lane integration, no toast suggestions, no light
writes — those layer on after the 2-week Spearman ρ > 0.4 calibration
gate.

Audio prosody (planned 0.3 weight on arousal) is deferred to a follow-up
because it requires extending audio_classifier to expose RMS + spectral
features. Phase A is face-only; ``factors`` JSON includes an explicit
``audio_arousal: null`` marker so the calibration UI can show which
inputs were live.

Privacy: blendshape values are tiny floats already derived from the face
crop inside camera_service's executor — by the time they reach this
service the raw frame has been dereferenced. We persist only the derived
V/A/F floats and the top-3 contributing blendshapes (for debuggability),
never coordinates.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.models import MoodSample
from backend.services.ml.health_mixin import HealthTrackable

logger = logging.getLogger("home_hub.personality.emotion")

# How often we walk the last-blendshape cache and persist a mood_samples
# row. Camera fires blendshapes every ~2s (camera POLL_INTERVAL) when
# emotion is enabled; persisting every 10s gives ~5 rows per minute,
# tractable for the rolling 7-day window without flooding the DB.
PERSIST_INTERVAL_S = 10.0

# After this many seconds without a fresh blendshape callback the cached
# mood vector is considered stale and get_current() returns None. Keeps
# the calibration UI honest about whether the camera is currently giving
# us a face read.
STALE_AFTER_S = 30.0

# EMA mirrors the lighting learner's α=0.3 (~3-4 samples to 95%). At a 2s
# poll cadence that's ~10s to converge, fast enough to feel responsive
# but slow enough to dampen single-frame oddities (closed-eye blink, half-
# turned head between frames).
EMA_ALPHA = 0.3

# Per-source freshness window. When both the Latitude camera_service
# callback and the desktop pc_agent are feeding blendshapes, the desktop
# source wins as long as its last submit is within this window — the
# Latitude path then short-circuits to avoid noisy averaging across two
# very different capture geometries (corner three-quarter profile vs.
# desktop frontal). After the desktop goes silent (Zoom lock, user
# leaves the desk) the Latitude path picks back up at next callback.
DESKTOP_FRESHNESS_S = 30.0

# Below this face confidence we don't update the EMA — a barely-detected
# face produces garbage blendshapes that, if averaged in, drag the EMA
# toward whatever the noisy reading was. Matches camera_service's
# FACE_TRUST_THRESHOLD posture: trust strong reads, ignore weak ones.
MIN_FACE_CONFIDENCE_FOR_UPDATE = 0.30


# ARKit blendshape names → (valence, arousal, focus) coefficient.
# Hand-tuned starting point — the calibration UI will fit per-axis bias
# corrections on top, but the COEFFICIENTS themselves are static (we want
# them interpretable, not learned). Coverage is intentionally sparse:
# only the blendshapes with established psychological grounding are
# included; the rest contribute zero.
_BLENDSHAPE_COEFFS: dict[str, tuple[float, float, float]] = {
    # Smile family — primary valence positive signal. Cheek-squint is the
    # Duchenne marker (genuine vs polite smile); double-weighting it on
    # valence rewards real grins.
    "mouthSmileLeft":    (+0.50, +0.10,  0.00),
    "mouthSmileRight":   (+0.50, +0.10,  0.00),
    "cheekSquintLeft":   (+0.25,  0.00,  0.00),
    "cheekSquintRight":  (+0.25,  0.00,  0.00),
    # Frown family — primary valence negative signal.
    "mouthFrownLeft":    (-0.50, -0.10,  0.00),
    "mouthFrownRight":   (-0.50, -0.10,  0.00),
    # Brow-down — anger / focus / annoyance. V-, A+.
    "browDownLeft":      (-0.20, +0.30,  0.00),
    "browDownRight":     (-0.20, +0.30,  0.00),
    # Brow-inner-up — sadness/concern. V-, slight A+.
    "browInnerUp":       (-0.30, +0.10,  0.00),
    # Brow-outer-up — surprise. A+.
    "browOuterUpLeft":   ( 0.00, +0.25,  0.00),
    "browOuterUpRight":  ( 0.00, +0.25,  0.00),
    # Jaw open — surprise/yelling. Strong arousal+.
    "jawOpen":           ( 0.00, +0.40,  0.00),
    # Mouth press — stress/tension. V-, A+.
    "mouthPressLeft":    (-0.20, +0.30,  0.00),
    "mouthPressRight":   (-0.20, +0.30,  0.00),
    # Nose sneer — disgust. V-, A+.
    "noseSneerLeft":     (-0.30, +0.20,  0.00),
    "noseSneerRight":    (-0.30, +0.20,  0.00),
    # Blink — distraction signal (high blink rate ⇒ focus drop). Single-
    # frame blinks are unavoidable; the EMA dampens them.
    "eyeBlinkLeft":      ( 0.00,  0.00, -0.30),
    "eyeBlinkRight":     ( 0.00,  0.00, -0.30),
    # Squint — focus signal. People squint at small text / hard work.
    "eyeSquintLeft":     ( 0.00,  0.00, +0.30),
    "eyeSquintRight":    ( 0.00,  0.00, +0.30),
    # Gaze in (toward monitor) — focus+. Gaze out — focus-.
    # These are noisy in three-quarter profile but cheap to include.
    "eyeLookInLeft":     ( 0.00,  0.00, +0.20),
    "eyeLookInRight":    ( 0.00,  0.00, +0.20),
    "eyeLookOutLeft":    ( 0.00,  0.00, -0.20),
    "eyeLookOutRight":   ( 0.00,  0.00, -0.20),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _blendshapes_to_vaf(
    blendshapes: dict[str, float],
) -> tuple[float, float, float, list[tuple[str, float]]]:
    """Linear projection of 52 blendshape values to (V, A, F).

    Returns the V/A/F triple plus a list of the top-3 contributing
    blendshape names (sorted by absolute value) for explainability.
    """
    v = a = f = 0.0
    for name, value in blendshapes.items():
        coef = _BLENDSHAPE_COEFFS.get(name)
        if coef is None:
            continue
        cv, ca, cf = coef
        v += cv * value
        a += ca * value
        f += cf * value

    v = _clamp(v, -1.0, 1.0)
    a = _clamp(a, -1.0, 1.0)
    # Focus is one-sided [0, 1]. We accumulated signed deltas; map back by
    # shifting the neutral point to 0.5 and clamping.
    f = _clamp(0.5 + f, 0.0, 1.0)

    # Top-3 most-active blendshapes for debugging — useful when the
    # detector says "stressed" and we want to know which input drove it.
    top = sorted(
        ((n, val) for n, val in blendshapes.items() if val > 0.05),
        key=lambda kv: kv[1],
        reverse=True,
    )[:3]

    return v, a, f, top


class EmotionService(HealthTrackable):
    """Face blendshapes → mood vector (V/A/F) → mood_samples shadow log.

    Shape mirrors NotifierService:
      - construct with collaborators
      - async start() / close() lifecycle
      - async poll_loop() / on_blendshape() callback
      - HealthTrackable for /health surface
    """

    def __init__(
        self,
        ws_manager,
        automation_engine,
        camera_service,
        session_factory: async_sessionmaker,
    ) -> None:
        self._ws = ws_manager
        self._engine = automation_engine
        self._camera = camera_service
        self._session_factory = session_factory

        self._enabled = False  # gated by emotion_enabled setting
        self._lock = asyncio.Lock()
        self._last_vector: Optional[dict[str, Any]] = None
        self._last_persist_at: float = 0.0
        self._poll_task: Optional[asyncio.Task] = None
        self._closed = False
        # Per-source last-seen timestamps for the dual-source preference
        # logic (Latitude camera_service callback vs. desktop pc_agent
        # POST). Desktop wins within DESKTOP_FRESHNESS_S; Latitude
        # short-circuits when desktop is fresh. Phase A GH#64.
        self._last_source_seen: dict[str, datetime] = {}

        # Per-user calibration bias (added to live readings at output time).
        # Loaded from app_settings["mood_calibration_bias"] when present.
        self._bias_valence = 0.0
        self._bias_arousal = 0.0
        self._bias_focus = 0.0

        self._init_health_tracking(failure_threshold=5)
        logger.info("EmotionService initialized (shadow-log only)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_vector(self) -> Optional[dict[str, Any]]:
        """Snapshot of the last mood reading — used by API + Mood-Ring."""
        return self._last_vector

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, emotion_enabled: bool) -> None:
        """Subscribe to camera blendshapes and start the persist loop."""
        await self._load_bias()
        self._enabled = bool(emotion_enabled)
        if self._camera is not None:
            try:
                self._camera.register_blendshape_callback(self.on_blendshape)
                self._camera.set_emotion_enabled(self._enabled)
            except AttributeError:
                # Older camera_service without the hooks — degrade gracefully.
                logger.warning(
                    "camera_service has no emotion hooks; EmotionService idle"
                )
                self._enabled = False
        else:
            logger.info(
                "EmotionService: camera_service unavailable; mood will stay null"
            )

        if self._enabled and self._poll_task is None:
            self._poll_task = asyncio.create_task(self.poll_loop())

    async def close(self) -> None:
        self._closed = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None

    async def set_enabled(self, enabled: bool) -> None:
        """Flip the opt-in toggle at runtime (called by routes/personality)."""
        self._enabled = bool(enabled)
        if self._camera is not None:
            try:
                self._camera.set_emotion_enabled(self._enabled)
            except AttributeError:
                pass

        if self._enabled and self._poll_task is None:
            self._poll_task = asyncio.create_task(self.poll_loop())
        elif not self._enabled and self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
            self._last_vector = None  # don't strand a stale reading

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    async def on_blendshape(
        self,
        blendshapes: dict[str, float],
        face_confidence: float,
        timestamp: datetime,
        source: str = "latitude",
    ) -> None:
        """Callback fired per detection cycle when emotion is enabled.

        Two sources feed this: the Latitude `camera_service` callback
        (default, ``source="latitude"``) and the desktop pc_agent over
        HTTP POST (``source="desktop"``, GH#64). The desktop wins when
        fresh — its capture geometry is frontal, which is materially
        better for the ARKit blendshape projection. The Latitude path
        keeps the bed scenario covered.
        """
        if not self._enabled or self._closed:
            return
        if face_confidence < MIN_FACE_CONFIDENCE_FOR_UPDATE:
            return

        # Dual-source preference: when the desktop is fresh, drop incoming
        # Latitude callbacks rather than EMA-blending them. The two
        # capture geometries are too different to average cleanly.
        if source == "latitude":
            desktop_last = self._last_source_seen.get("desktop")
            if desktop_last is not None:
                age = (datetime.now(timezone.utc) - desktop_last).total_seconds()
                if age < DESKTOP_FRESHNESS_S:
                    return

        # Don't track emotion during sleeping mode — the camera is paused
        # anyway, but this is defense-in-depth if the pause races.
        try:
            mode = getattr(self._engine, "current_mode", None)
        except Exception:
            mode = None
        if mode == "sleeping":
            return

        try:
            v, a, f, top = _blendshapes_to_vaf(blendshapes)
        except Exception as exc:
            self._track_predict(False, exc)
            logger.exception("blendshape→VAF projection failed")
            return

        # Apply per-user bias correction (defaults to zero pre-calibration).
        v = _clamp(v + self._bias_valence, -1.0, 1.0)
        a = _clamp(a + self._bias_arousal, -1.0, 1.0)
        f = _clamp(f + self._bias_focus, 0.0, 1.0)

        # EMA-smooth against the previous reading.
        async with self._lock:
            prev = self._last_vector
            if prev is not None and (
                datetime.now(timezone.utc) - prev["ts"]
            ).total_seconds() < STALE_AFTER_S:
                v = EMA_ALPHA * v + (1 - EMA_ALPHA) * prev["valence"]
                a = EMA_ALPHA * a + (1 - EMA_ALPHA) * prev["arousal"]
                f = EMA_ALPHA * f + (1 - EMA_ALPHA) * prev["focus"]

            self._last_vector = {
                "valence": v,
                "arousal": a,
                "focus": f,
                "confidence": face_confidence,
                "ts": timestamp,
                "factors": {
                    "face_confidence": face_confidence,
                    "audio_arousal": None,  # phase A: face-only
                    "source": source,
                    "top_blendshapes": [
                        {"name": n, "value": float(val)} for n, val in top
                    ],
                },
            }
            self._last_source_seen[source] = timestamp
        self._track_predict(True)

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------

    def get_current(self) -> Optional[dict[str, Any]]:
        """Return the last fresh mood reading or None if stale/missing."""
        snap = self._last_vector
        if snap is None:
            return None
        age = (datetime.now(timezone.utc) - snap["ts"]).total_seconds()
        if age > STALE_AFTER_S:
            return None
        return {
            "valence": snap["valence"],
            "arousal": snap["arousal"],
            "focus": snap["focus"],
            "confidence": snap["confidence"],
            "ts": snap["ts"].isoformat(),
            "age_seconds": age,
            "factors": snap["factors"],
        }

    async def poll_loop(self) -> None:
        """Persist a mood_samples row every PERSIST_INTERVAL_S when fresh."""
        while not self._closed:
            try:
                await self._maybe_persist()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("emotion poll iteration failed")
            await asyncio.sleep(PERSIST_INTERVAL_S)

    async def _maybe_persist(self) -> None:
        snap = self._last_vector
        if snap is None:
            return
        age = (datetime.now(timezone.utc) - snap["ts"]).total_seconds()
        if age > STALE_AFTER_S:
            return

        try:
            async with self._session_factory() as session:
                session.add(
                    MoodSample(
                        timestamp=snap["ts"],
                        valence=float(snap["valence"]),
                        arousal=float(snap["arousal"]),
                        focus=float(snap["focus"]),
                        confidence=float(snap["confidence"]),
                        factors=snap["factors"],
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("mood_samples persist failed")

    async def _load_bias(self) -> None:
        """Load per-user calibration bias from app_settings (if present)."""
        try:
            from backend.api.routes.routines import load_setting
            cfg = await load_setting("mood_calibration_bias")
            if isinstance(cfg, dict):
                self._bias_valence = float(cfg.get("valence", 0.0))
                self._bias_arousal = float(cfg.get("arousal", 0.0))
                self._bias_focus = float(cfg.get("focus", 0.0))
        except Exception:
            logger.debug("mood_calibration_bias not loaded", exc_info=True)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_status(self) -> dict[str, Any]:
        """Public health() with personality-layer-specific extras."""
        snap = self._last_vector
        extras: dict[str, Any] = {
            "enabled": self._enabled,
            "last_vector_age_seconds": (
                (datetime.now(timezone.utc) - snap["ts"]).total_seconds()
                if snap is not None
                else None
            ),
        }
        return self.health(
            is_shadow=True,  # Phase A: shadow-only by design
            model_loaded=self._camera is not None,
            extra=extras,
        )
