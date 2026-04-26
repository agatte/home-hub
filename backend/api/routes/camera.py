"""Camera presence detection endpoints — status, enable/disable, calibrate."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.camera")

router = APIRouter(prefix="/api/camera", tags=["camera"])


class CameraToggle(BaseModel):
    """Request body for enabling/disabling the camera."""

    enabled: bool


def _current_multiplier(service) -> float:
    """Current lux multiplier for the UI readout (1.0 if uncalibrated / stale)."""
    from datetime import datetime, timezone

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


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Return camera service status (includes lux calibration + current multiplier)."""
    service = getattr(request.app.state, "camera_service", None)
    if service is None:
        return {"status": "ok", "enabled": False, "available": False}
    return {
        "status": "ok",
        **service.get_status(),
        "current_multiplier": _current_multiplier(service),
    }


@router.get("/snapshot")
async def get_snapshot(request: Request, annotate: bool = False) -> Response:
    """Return a single JPEG frame from the webcam.

    Opt-in: requires ``camera_enabled``. The frame is captured through the
    running camera service (shares the existing ``cv2.VideoCapture`` handle)
    and is never written to disk or cached server-side. When ``annotate`` is
    true, the response overlays the face bounding box and the current lux +
    multiplier readout for framing / calibration verification.
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
    from backend.api.routes.routines import load_setting, save_setting

    await save_setting("camera_enabled", {"enabled": body.enabled})

    if body.enabled:
        # Start camera service if not already running
        service = getattr(request.app.state, "camera_service", None)
        if service and service.enabled:
            return {"status": "ok", "detail": "Camera already enabled"}

        try:
            import asyncio

            from backend.services.camera_service import CameraService

            ws_manager = request.app.state.ws_manager
            automation = request.app.state.automation
            ml_logger = getattr(request.app.state, "ml_logger", None)

            camera = CameraService(ws_manager, automation, ml_logger)
            await camera.start()

            if camera.enabled:
                request.app.state.camera_service = camera
                automation.register_on_mode_change(camera.on_mode_change)
                automation.set_camera_service(camera)
                asyncio.create_task(camera.poll_loop())
                logger.info("Camera service started via API toggle")
                return {"status": "ok", "detail": "Camera enabled", **camera.get_status()}
            else:
                return {
                    "status": "error",
                    "detail": "Camera unavailable (may be in use or missing)",
                }
        except ImportError as exc:
            logger.warning("Cannot enable camera — missing dependency: %s", exc)
            return {
                "status": "error",
                "detail": f"Missing dependency: {exc}",
            }
    else:
        # Stop camera service
        service = getattr(request.app.state, "camera_service", None)
        if service:
            await service.close()
            request.app.state.camera_service = None
            automation = request.app.state.automation
            automation.set_camera_service(None)
            logger.info("Camera service stopped via API toggle")
        return {"status": "ok", "detail": "Camera disabled"}
