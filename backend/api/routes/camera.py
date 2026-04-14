"""Camera presence detection endpoints — status, enable/disable toggle."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("home_hub.camera")

router = APIRouter(prefix="/api/camera", tags=["camera"])


class CameraToggle(BaseModel):
    """Request body for enabling/disabling the camera."""

    enabled: bool


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Return camera service status."""
    service = getattr(request.app.state, "camera_service", None)
    if service is None:
        return {"status": "ok", "enabled": False, "available": False}
    return {"status": "ok", **service.get_status()}


@router.post("/enable")
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
            logger.info("Camera service stopped via API toggle")
        return {"status": "ok", "detail": "Camera disabled"}
