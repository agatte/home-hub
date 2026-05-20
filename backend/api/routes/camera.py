"""Camera presence detection endpoints — status, enable/disable, calibrate."""

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.api.auth import require_api_key
from backend.services.presence_fusion import KNOWN_SOURCES, PresenceReading

logger = logging.getLogger("home_hub.camera")

router = APIRouter(prefix="/api/camera", tags=["camera"])


class CameraToggle(BaseModel):
    """Request body for enabling/disabling the camera."""

    enabled: bool


class PresenceObservation(BaseModel):
    """One presence reading from an off-host source (currently desktop pc_agent).

    Fields mirror ``PresenceReading`` — the route builds the dataclass
    from this body and hands it to ``app.state.presence``.
    """

    source: Literal["desktop"] = "desktop"
    captured_at: Optional[datetime] = None
    face_present: Optional[bool] = None
    face_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    detection_source: Optional[Literal["face", "pose"]] = None
    zone: Optional[Literal["desk", "bed"]] = None
    posture: Optional[Literal["upright", "reclined", "slouched"]] = None
    posture_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pose_visible_landmarks: Optional[int] = Field(default=None, ge=0)


def _current_multiplier(service) -> float:
    """Current lux multiplier for the UI readout (1.0 if uncalibrated / stale)."""
    from backend.services.automation_engine import LUX_STALE_SECONDS, lux_to_multiplier

    ema = getattr(service, "ema_lux", None)
    if ema is None:
        return 1.0
    last = getattr(service, "last_lux_update", None)
    if last is None:
        return 1.0
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age > LUX_STALE_SECONDS:
        return 1.0
    baseline = getattr(service, "baseline_lux", None)
    return lux_to_multiplier(float(ema), float(baseline) if baseline else 90.0)


@router.get("/status", dependencies=[Depends(require_api_key)])
async def get_status(request: Request) -> dict:
    """Return camera service status (includes lux calibration + current multiplier).

    Gated even though it's a GET — the response leaks zone, posture, lux,
    and the calibration baseline, all of which are useful reconnaissance
    for a public-tunnel attacker. LAN dashboards keep working via the
    RFC1918 bypass in `require_api_key`.
    """
    service = getattr(request.app.state, "camera_service", None)
    presence = getattr(request.app.state, "presence", None)
    presence_block = presence.get_status() if presence is not None else None

    if service is None:
        return {
            "status": "ok",
            "enabled": False,
            "available": False,
            "presence": presence_block,
        }
    return {
        "status": "ok",
        **service.get_status(),
        "current_multiplier": _current_multiplier(service),
        "presence": presence_block,
    }


@router.post("/observation", dependencies=[Depends(require_api_key)])
async def post_observation(
    payload: PresenceObservation, request: Request,
) -> dict:
    """Ingest a presence reading from an off-host source (desktop pc_agent).

    The desktop emotion_capture POSTs here after each FaceLandmarker tick
    when ``desktop_presence_enabled`` is on. The Latitude camera reaches
    PresenceFusion directly via in-process callback; this endpoint is
    the network boundary for everything else.

    LAN-bypass at ``auth.py:90`` covers the 192.168.1.30 desktop. The
    ``require_api_key`` dependency stays for shape consistency and for
    future tunnel-origin sources (e.g. a phone-camera companion app).
    """
    if payload.source not in KNOWN_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"unknown source: {payload.source}",
        )

    presence = getattr(request.app.state, "presence", None)
    if presence is None:
        # Service hasn't started (early-boot race, or unit-test). Don't
        # error — silent drops here are safer than 503s that retry-storm
        # an agent during startup. Logged for observability.
        logger.debug(
            "presence observation dropped — PresenceFusion not initialized"
        )
        return {"status": "ok", "detail": "presence service unavailable"}

    reading = PresenceReading(
        source=payload.source,
        captured_at=payload.captured_at or datetime.now(timezone.utc),
        face_present=payload.face_present,
        face_confidence=payload.face_confidence,
        detection_source=payload.detection_source,
        zone=payload.zone,
        posture=payload.posture,
        posture_confidence=payload.posture_confidence,
        pose_visible_landmarks=payload.pose_visible_landmarks,
    )
    presence.on_observation(reading)
    return {"status": "ok"}


@router.get("/snapshot", dependencies=[Depends(require_api_key)])
async def get_snapshot(request: Request, annotate: bool = False) -> Response:
    """Return a single JPEG frame from the webcam.

    Opt-in: requires ``camera_enabled``. The frame is captured through the
    running camera service (shares the existing ``cv2.VideoCapture`` handle)
    and is never written to disk or cached server-side. When ``annotate`` is
    true, the response overlays the face bounding box and the current lux +
    multiplier readout for framing / calibration verification.

    **Auth-gated** (defense in depth — the tunnel allowlist already
    excludes this path, but the gate ensures any future remote-app path
    that bypasses the allowlist still can't pull JPEGs of the apartment).
    """
    service = getattr(request.app.state, "camera_service", None)
    if service is None or not service.enabled:
        raise HTTPException(status_code=409, detail="camera is not enabled")
    if getattr(service, "_paused", False):
        raise HTTPException(status_code=503, detail="camera paused (sleeping mode)")
    jpeg = await service.capture_snapshot(annotate=annotate)
    if jpeg is None:
        raise HTTPException(status_code=503, detail="capture failed")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/calibrate", dependencies=[Depends(require_api_key)])
async def calibrate_exposure(request: Request) -> dict:
    """Calibrate fixed exposure so gray.mean() ≈ 100 under current room light.

    Must be called with the camera enabled and during lighting representative
    of your typical usage (normal evening room light works well). Binary-
    searches ``CAP_PROP_EXPOSURE`` until the calibration target is hit, then
    persists the result to ``app_settings`` so future restarts re-apply it.
    """
    service = getattr(request.app.state, "camera_service", None)
    if service is None or not service.enabled:
        raise HTTPException(status_code=409, detail="camera is not enabled")
    result = await service.calibrate_exposure()
    if result.get("status") != "ok":
        raise HTTPException(status_code=500, detail=result.get("detail", "calibration failed"))
    return result


@router.post("/enable", dependencies=[Depends(require_api_key)])
async def toggle_camera(body: CameraToggle, request: Request) -> dict:
    """Enable or disable camera presence detection.

    When enabling: initializes the camera service if not already running.
    When disabling: stops the camera and releases resources.
    """
    from backend.api.routes.routines import save_setting

    await save_setting("camera_enabled", {"enabled": body.enabled})

    if body.enabled:
        try:
            from backend.services.camera_service import spawn_camera_service
            result = await spawn_camera_service(request.app, reason="api_toggle")
        except ImportError as exc:
            logger.warning("Cannot enable camera — missing dependency: %s", exc)
            return {
                "status": "error",
                "detail": f"Missing dependency: {exc}",
            }
        return result

    # Disable path. Tear down any existing service; tolerate a half-dead
    # one (close() is idempotent and releases V4L2 even when _enabled is
    # already False from a crashed poll_loop).
    service = getattr(request.app.state, "camera_service", None)
    if service is not None:
        try:
            await service.close()
        except Exception:
            logger.exception("Camera close() raised during disable — continuing")
        request.app.state.camera_service = None
        automation = request.app.state.automation
        automation.set_camera_service(None)
        logger.info("Camera service stopped via API toggle")
    return {"status": "ok", "detail": "Camera disabled"}


# spawn_camera_service lives in backend.services.camera_service so the
# watchdog loop (also in that module) can share it without creating an
# api → service → api import cycle. The route imports it lazily inside
# the handler above.
