"""
Hue light control endpoints.
"""
from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas.lights import LightResponse, LightState

router = APIRouter(prefix="/api/lights", tags=["lights"])


@router.get("", response_model=list[LightResponse])
async def get_all_lights(request: Request) -> list[dict]:
    """Get the current state of all Hue lights."""
    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")
    return await hue.get_all_lights()


@router.get("/{light_id}", response_model=LightResponse)
async def get_light(light_id: str, request: Request) -> dict:
    """Get the current state of a single light."""
    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    light = await hue.get_light(light_id)
    if not light:
        raise HTTPException(status_code=404, detail=f"Light {light_id} not found")
    return light


@router.put("/{light_id}")
async def set_light(light_id: str, state: LightState, request: Request) -> dict:
    """
    Set the state of a single light.

    Any combination of on, bri, hue, sat can be provided.
    """
    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    state_dict = state.model_dump(exclude_none=True)
    if not state_dict:
        raise HTTPException(status_code=400, detail="No state values provided")

    success = await hue.set_light(light_id, state_dict)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set light state")

    # Broadcast update to WebSocket clients
    updated = await hue.get_light(light_id)
    if updated:
        ws_manager = request.app.state.ws_manager
        await ws_manager.broadcast("light_update", updated)

    return {"status": "ok", "light_id": light_id}


@router.post("/all")
async def set_all_lights(state: LightState, request: Request) -> dict:
    """Set the same state on all lights (used for scenes)."""
    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    state_dict = state.model_dump(exclude_none=True)
    if not state_dict:
        raise HTTPException(status_code=400, detail="No state values provided")

    success = await hue.set_all_lights(state_dict)

    # Broadcast all light updates
    ws_manager = request.app.state.ws_manager
    lights = await hue.get_all_lights()
    for light in lights:
        await ws_manager.broadcast("light_update", light)

    return {"status": "ok" if success else "partial_failure"}
