"""AI Personality Layer routes — mood readings + calibration + settings.

Phase A (shadow-log only): read the live mood vector, store self-report
calibration rows against detector readings, expose 7-day history. No
actuation surfaces here yet — the mood-ring light (Phase B) and vibe
intent (Phase C) will add their own endpoints when they ship.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from backend.api.auth import require_api_key
from backend.api.routes.routines import load_setting, save_setting
from backend.database import async_session
from backend.models import MoodCalibration, MoodSample
from backend.services.personality.mood_palette import mood_to_hsv

logger = logging.getLogger("home_hub.personality")

router = APIRouter(prefix="/api/personality", tags=["personality"])

# Settings keys live in app_settings so the toggles survive restarts and
# Phase B's mood-ring service can read them independently of the route.
SETTING_PERSONALITY_ENABLED = "personality_enabled"
SETTING_EMOTION_ENABLED = "emotion_enabled"
SETTING_DESKTOP_EMOTION_ENABLED = "desktop_emotion_enabled"
SETTING_MOOD_RING_ENABLED = "mood_ring_enabled"
SETTING_MOOD_RING_LIGHT_ID = "mood_ring_light_id"
SETTING_CALIBRATION_BIAS = "mood_calibration_bias"

# Minimum self-report samples before we fit a per-user bias vector — under
# this we'd be overfitting to noise.
MIN_CALIBRATION_SAMPLES_FOR_BIAS_FIT = 10


def _emotion_service(request: Request):
    return getattr(request.app.state, "emotion_service", None)


# ---------------------------------------------------------------------------
# Mood reading
# ---------------------------------------------------------------------------

@router.get("/mood/current")
async def get_mood_current(request: Request) -> dict:
    """Return the live mood vector or null when stale / disabled."""
    svc = _emotion_service(request)
    if svc is None:
        return {"vector": None, "enabled": False, "reason": "service_unavailable"}
    if not svc.enabled:
        return {"vector": None, "enabled": False, "reason": "emotion_disabled"}
    vec = svc.get_current()
    if vec is None:
        return {
            "vector": None,
            "enabled": True,
            "reason": "no_fresh_face",
        }
    h, s, b = mood_to_hsv(
        vec["valence"], vec["arousal"], vec["focus"], vec["confidence"],
    )
    return {
        "vector": vec,
        "enabled": True,
        "preview_hsv": {"hue": h, "sat": s, "bri": b},
    }


@router.get("/mood/history")
async def get_mood_history(hours: int = 24) -> dict:
    """Return mood_samples rows for the last ``hours`` hours.

    Capped at 168 (7 days) to match the rolling retention window. Returns
    a list of dicts in ascending timestamp order for easy charting.
    """
    hours = max(1, min(168, int(hours)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with async_session() as session:
        result = await session.execute(
            select(MoodSample)
            .where(MoodSample.timestamp >= cutoff)
            .order_by(MoodSample.timestamp.asc())
        )
        rows = result.scalars().all()

    return {
        "hours": hours,
        "count": len(rows),
        "samples": [
            {
                "timestamp": r.timestamp.isoformat(),
                "valence": r.valence,
                "arousal": r.arousal,
                "focus": r.focus,
                "confidence": r.confidence,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class CalibrationSubmit(BaseModel):
    """User's self-report against the detector's live reading.

    Sliders run -1..1 for V/A and 0..1 for F; values outside that are
    clamped server-side. Detector fields are optional — the UI snapshots
    them from /mood/current at form open and posts them back.
    """
    self_valence: float = Field(ge=-1.0, le=1.0)
    self_arousal: float = Field(ge=-1.0, le=1.0)
    self_focus: float = Field(ge=0.0, le=1.0)
    detected_valence: Optional[float] = None
    detected_arousal: Optional[float] = None
    detected_focus: Optional[float] = None
    detected_confidence: Optional[float] = None


@router.post("/calibration", dependencies=[Depends(require_api_key)])
async def post_calibration(payload: CalibrationSubmit) -> dict:
    """Save one self-report row and refit the per-axis bias if enough samples."""
    async with async_session() as session:
        row = MoodCalibration(
            self_valence=payload.self_valence,
            self_arousal=payload.self_arousal,
            self_focus=payload.self_focus,
            detected_valence=payload.detected_valence,
            detected_arousal=payload.detected_arousal,
            detected_focus=payload.detected_focus,
            detected_confidence=payload.detected_confidence,
        )
        session.add(row)
        await session.commit()

    bias = await _maybe_refit_bias()
    return {"status": "ok", "bias": bias}


@router.get("/calibration/history")
async def get_calibration_history(limit: int = 50) -> dict:
    limit = max(1, min(500, int(limit)))
    async with async_session() as session:
        result = await session.execute(
            select(MoodCalibration)
            .order_by(desc(MoodCalibration.timestamp))
            .limit(limit)
        )
        rows = result.scalars().all()

    return {
        "count": len(rows),
        "samples": [
            {
                "timestamp": r.timestamp.isoformat(),
                "self": {"valence": r.self_valence, "arousal": r.self_arousal, "focus": r.self_focus},
                "detected": (
                    {
                        "valence": r.detected_valence,
                        "arousal": r.detected_arousal,
                        "focus": r.detected_focus,
                        "confidence": r.detected_confidence,
                    }
                    if r.detected_valence is not None
                    else None
                ),
            }
            for r in rows
        ],
    }


async def _maybe_refit_bias() -> dict:
    """Compute a per-axis bias = mean(self - detected) over recent samples.

    Only refit once we have at least MIN_CALIBRATION_SAMPLES_FOR_BIAS_FIT
    matched (detector-non-null) self-reports. Bias is persisted to
    app_settings; takes effect at next server restart (when
    ``EmotionService.start()`` calls ``_load_bias()``). Phase B prep
    will add ``await self._load_bias()`` inside ``set_enabled`` for
    live-reload, but Phase A only reloads at boot.
    """
    async with async_session() as session:
        result = await session.execute(
            select(MoodCalibration)
            .where(MoodCalibration.detected_valence.is_not(None))
            .order_by(desc(MoodCalibration.timestamp))
            .limit(200)
        )
        rows = result.scalars().all()

    if len(rows) < MIN_CALIBRATION_SAMPLES_FOR_BIAS_FIT:
        return {
            "valence": 0.0, "arousal": 0.0, "focus": 0.0,
            "samples_used": len(rows),
            "fit": False,
            "reason": f"need_at_least_{MIN_CALIBRATION_SAMPLES_FOR_BIAS_FIT}_samples",
        }

    def _mean_delta(self_attr: str, det_attr: str) -> float:
        deltas = [
            getattr(r, self_attr) - getattr(r, det_attr)
            for r in rows
            if getattr(r, det_attr) is not None
        ]
        return sum(deltas) / len(deltas) if deltas else 0.0

    bias = {
        "valence": max(-0.5, min(0.5, _mean_delta("self_valence", "detected_valence"))),
        "arousal": max(-0.5, min(0.5, _mean_delta("self_arousal", "detected_arousal"))),
        # Focus is one-sided [0, 1] so we cap the magnitude harder.
        "focus": max(-0.3, min(0.3, _mean_delta("self_focus", "detected_focus"))),
    }
    await save_setting(SETTING_CALIBRATION_BIAS, bias)
    return {**bias, "samples_used": len(rows), "fit": True}


# ---------------------------------------------------------------------------
# Blendshape ingest (Phase A — GH#64 dual-source capture)
#
# Latitude camera_service feeds EmotionService.on_blendshape directly via
# its in-process callback. The desktop pc_agent (backend/services/pc_agent/
# emotion_capture.py) runs FaceLandmarker locally and POSTs the same
# 52-float blendshape dict here. Privacy contract: raw frames never cross
# the network; only the derived float dict + confidence + timestamp do.
# Mirrors `camera_service.py` lines 18-25.
# ---------------------------------------------------------------------------

class BlendshapeSubmit(BaseModel):
    """One desktop-captured FaceLandmarker reading."""

    blendshapes: dict[str, float] = Field(..., min_length=1)
    # Note: source="desktop" sends a max-non-neutral-blendshape proxy
    # (FaceLandmarker has no top-level detector score); source="latitude"
    # sends the BlazeFace top-category score. Both gate on 0.30 empirically
    # but don't compare magnitudes across sources for confidence-weighted logic.
    face_confidence: float = Field(..., ge=0.0, le=1.0)
    source: Literal["desktop", "latitude"] = "desktop"
    timestamp: Optional[datetime] = None


@router.post("/blendshape", dependencies=[Depends(require_api_key)])
async def post_blendshape(payload: BlendshapeSubmit, request: Request) -> dict:
    """Ingest a blendshape reading from the desktop pc_agent.

    LAN-bypass at `auth.py:90` covers Anthony's 192.168.1.30 desktop —
    the `require_api_key` dependency stays for shape consistency and
    future-proofing if this ever needs to accept tunnel-origin traffic.

    The desktop posts only the 52 derived float values plus a confidence
    scalar and a timestamp; raw frames live in-memory on the desktop and
    are dereferenced after the FaceLandmarker pass. This route is the
    network boundary for that contract.
    """
    svc = _emotion_service(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="emotion_service unavailable")

    # Pydantic enforces dict[str, float] coercion but not per-value ranges;
    # validate [0, 1] bounds inline.
    for name, value in payload.blendshapes.items():
        if value < 0.0 or value > 1.0:
            raise HTTPException(
                status_code=400,
                detail=f"blendshape '{name}' out of range [0, 1]: {value}",
            )

    ts = payload.timestamp or datetime.now(timezone.utc)
    await svc.on_blendshape(
        payload.blendshapes,
        float(payload.face_confidence),
        ts,
        source=payload.source,
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class PersonalitySettings(BaseModel):
    personality_enabled: Optional[bool] = None
    emotion_enabled: Optional[bool] = None
    desktop_emotion_enabled: Optional[bool] = None
    mood_ring_enabled: Optional[bool] = None
    mood_ring_light_id: Optional[str] = None


@router.get("/settings")
async def get_settings() -> dict:
    return {
        "personality_enabled": (
            (await load_setting(SETTING_PERSONALITY_ENABLED)) or {}
        ).get("enabled", False),
        "emotion_enabled": (
            (await load_setting(SETTING_EMOTION_ENABLED)) or {}
        ).get("enabled", False),
        "desktop_emotion_enabled": (
            (await load_setting(SETTING_DESKTOP_EMOTION_ENABLED)) or {}
        ).get("enabled", False),
        "mood_ring_enabled": (
            (await load_setting(SETTING_MOOD_RING_ENABLED)) or {}
        ).get("enabled", False),
        "mood_ring_light_id": (
            (await load_setting(SETTING_MOOD_RING_LIGHT_ID)) or {}
        ).get("light_id", "1"),
        "calibration_bias": await load_setting(SETTING_CALIBRATION_BIAS) or {
            "valence": 0.0, "arousal": 0.0, "focus": 0.0,
        },
    }


@router.post("/settings", dependencies=[Depends(require_api_key)])
async def post_settings(payload: PersonalitySettings, request: Request) -> dict:
    """Update one or more personality sub-toggles. Returns the new state."""
    if payload.personality_enabled is not None:
        await save_setting(
            SETTING_PERSONALITY_ENABLED, {"enabled": payload.personality_enabled},
        )
    if payload.emotion_enabled is not None:
        await save_setting(
            SETTING_EMOTION_ENABLED, {"enabled": payload.emotion_enabled},
        )
        svc = _emotion_service(request)
        if svc is not None:
            await svc.set_enabled(payload.emotion_enabled)
    if payload.desktop_emotion_enabled is not None:
        # Desktop agent polls this setting on a 30s cadence to learn
        # whether it should be POSTing. No backend-side service to flip
        # — the pc_agent owns its own enable state.
        await save_setting(
            SETTING_DESKTOP_EMOTION_ENABLED,
            {"enabled": payload.desktop_emotion_enabled},
        )
    if payload.mood_ring_enabled is not None:
        await save_setting(
            SETTING_MOOD_RING_ENABLED, {"enabled": payload.mood_ring_enabled},
        )
    if payload.mood_ring_light_id is not None:
        await save_setting(
            SETTING_MOOD_RING_LIGHT_ID, {"light_id": payload.mood_ring_light_id},
        )
    return await get_settings()
