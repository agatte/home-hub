"""
Hue light control endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key
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


async def _log_light_change(
    request: Request,
    light_id: str,
    before: dict | None,
    state_dict: dict,
    trigger: str,
) -> None:
    """Fire-and-forget light adjustment log entry."""
    event_logger = getattr(request.app.state, "event_logger", None)
    automation = getattr(request.app.state, "automation", None)
    if not event_logger:
        return
    before = before or {}
    mode = automation.current_mode if automation else None
    await event_logger.log_light_adjustment(
        light_id=str(light_id),
        light_name=before.get("name"),
        bri_before=before.get("bri") if "bri" in state_dict else None,
        bri_after=state_dict.get("bri"),
        hue_before=before.get("hue") if "hue" in state_dict else None,
        hue_after=state_dict.get("hue"),
        sat_before=before.get("sat") if "sat" in state_dict else None,
        sat_after=state_dict.get("sat"),
        ct_before=before.get("ct") if "ct" in state_dict else None,
        ct_after=state_dict.get("ct"),
        mode_at_time=mode,
        trigger=trigger,
    )


@router.put("/{light_id}", dependencies=[Depends(require_api_key)])
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

    # Capture before-state for event logging
    before = await hue.get_light(light_id)

    success = await hue.set_light(light_id, state_dict)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set light state")

    # Mark this light as manually overridden so automation skips it
    automation = getattr(request.app.state, "automation", None)
    if automation:
        automation.mark_light_manual(str(light_id))

    # Broadcast update to WebSocket clients
    updated = await hue.get_light(light_id)
    if updated:
        ws_manager = request.app.state.ws_manager
        await ws_manager.broadcast("light_update", updated)

    await _log_light_change(request, light_id, before, state_dict, trigger="rest")
    return {"status": "ok", "light_id": light_id}


@router.post("/all", dependencies=[Depends(require_api_key)])
async def set_all_lights(state: LightState, request: Request) -> dict:
    """Set the same state on all lights (used for scenes)."""
    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    state_dict = state.model_dump(exclude_none=True)
    if not state_dict:
        raise HTTPException(status_code=400, detail="No state values provided")

    # Capture before-state for every light so we can log each individually
    before_lights = {l["light_id"]: l for l in await hue.get_all_lights()}

    success = await hue.set_all_lights(state_dict)

    # Broadcast all light updates
    ws_manager = request.app.state.ws_manager
    lights = await hue.get_all_lights()
    for light in lights:
        await ws_manager.broadcast("light_update", light)

    # Log one adjustment per light
    for lid, before in before_lights.items():
        await _log_light_change(
            request, lid, before, state_dict, trigger="all_lights"
        )

    return {"status": "ok" if success else "partial_failure"}
