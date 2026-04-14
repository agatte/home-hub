"""
Ambient sound endpoints — browser-based ambient audio control.

Manages playback state, volume, mode→sound mappings, and weather-reactive config.
Actual audio plays in the browser; these endpoints control what the backend
tells the frontend to play.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("home_hub.ambient_api")

router = APIRouter(prefix="/api/ambient", tags=["ambient"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AmbientPlayRequest(BaseModel):
    """Request to play a specific ambient sound."""
    filename: str = Field(..., min_length=1)


class AmbientVolumeRequest(BaseModel):
    """Request to set ambient volume."""
    volume: float = Field(..., ge=0.0, le=1.0)


class AmbientConfigUpdate(BaseModel):
    """Partial config update for ambient sound settings."""
    mode_sounds: Optional[dict[str, Optional[str]]] = None
    mode_auto_play: Optional[dict[str, bool]] = None
    weather_reactive: Optional[bool] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def get_ambient_state(request: Request) -> dict:
    """Full current state: playing, sound, volume, available sounds, config."""
    service = request.app.state.ambient_sound
    return service.get_state()


@router.get("/sounds")
async def list_sounds(request: Request) -> dict:
    """List available ambient sound files (rescans directory)."""
    service = request.app.state.ambient_sound
    sounds = service.scan_sounds()
    return {"status": "ok", "sounds": sounds}


@router.post("/play")
async def play_sound(body: AmbientPlayRequest, request: Request) -> dict:
    """Start playing a specific ambient sound."""
    service = request.app.state.ambient_sound
    return await service.play(body.filename)


@router.post("/pause")
async def pause_sound(request: Request) -> dict:
    """Pause current ambient sound."""
    service = request.app.state.ambient_sound
    return await service.pause()


@router.post("/resume")
async def resume_sound(request: Request) -> dict:
    """Resume paused ambient sound."""
    service = request.app.state.ambient_sound
    return await service.resume()


@router.post("/stop")
async def stop_sound(request: Request) -> dict:
    """Stop and clear ambient sound."""
    service = request.app.state.ambient_sound
    return await service.stop()


@router.post("/volume")
async def set_volume(body: AmbientVolumeRequest, request: Request) -> dict:
    """Set ambient volume (0.0-1.0)."""
    service = request.app.state.ambient_sound
    return await service.set_volume(body.volume)


@router.post("/config")
async def update_config(body: AmbientConfigUpdate, request: Request) -> dict:
    """Update ambient config (mode mappings, weather-reactive toggle)."""
    service = request.app.state.ambient_sound
    return await service.update_config(
        mode_sounds=body.mode_sounds,
        mode_auto_play=body.mode_auto_play,
        weather_reactive=body.weather_reactive,
    )
