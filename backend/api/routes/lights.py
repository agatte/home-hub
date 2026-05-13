"""
Hue light control endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api._guards import _check_hue_available
from backend.api.auth import require_api_key, source_from_request
from backend.api.schemas.lights import LightResponse, LightState

router = APIRouter(prefix="/api/lights", tags=["lights"])

# Relative brightness step (multiplicative). Mirrors the guest endpoint —
# 10% per tap, floor of 20 units so taps stay perceptible at low bri.
_BRIGHTNESS_STEP = 1.10
_BRIGHTNESS_MIN_STEP = 20


@router.get("", response_model=list[LightResponse])
async def get_all_lights(request: Request) -> list[dict]:
    """Get the current state of all Hue lights."""
    hue = request.app.state.hue
    _check_hue_available(hue)
    return await hue.get_all_lights()


@router.get("/{light_id}", response_model=LightResponse)
async def get_light(light_id: str, request: Request) -> dict:
    """Get the current state of a single light."""
    hue = request.app.state.hue
    _check_hue_available(hue)

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
    _check_hue_available(hue)

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

    # No post-write broadcast — the bridge is mid-transition and a fresh
    # read returns an intermediate value. Polling broadcasts after the
    # in-flight window (hue_service.poll_state_loop) and the frontend
    # optimistically patched its local store on the way in.

    await _log_light_change(
        request, light_id, before, state_dict,
        trigger=source_from_request(request, fallback="rest"),
    )
    return {"status": "ok", "light_id": light_id}


@router.post("/brightness/{direction}", dependencies=[Depends(require_api_key)])
async def adjust_brightness(direction: str, request: Request) -> dict:
    """Bump every on-light's brightness ±10%, clamped to the mode ceiling.

    Owner-facing counterpart to `/api/guest/brightness/{direction}`. Used by
    the Alexa skill ("brighter" / "dimmer"). No per-call cooldown — Alexa's
    own cadence + the engine's manual-override stamping are sufficient.
    """
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")

    hue = request.app.state.hue
    _check_hue_available(hue)

    automation = getattr(request.app.state, "automation", None)
    mode_mult = 1.0
    if automation:
        mode_mult = automation._mode_brightness.get(automation.current_mode, 1.0)
    ceiling = max(1, min(254, int(254 * mode_mult)))

    sign = 1 if direction == "up" else -1
    multiplicative_delta = _BRIGHTNESS_STEP - 1.0
    trigger = source_from_request(request, fallback="brightness_step")

    lights = await hue.get_all_lights()
    updated: list[dict] = []
    for light in lights:
        if not light.get("on") or "bri" not in light:
            continue
        current = light["bri"]
        delta = max(_BRIGHTNESS_MIN_STEP, round(current * multiplicative_delta))
        new_bri = max(1, min(ceiling, current + sign * delta))
        if new_bri == current:
            continue
        light_id = light["light_id"]
        await hue.set_light(light_id, {"bri": new_bri})
        if automation:
            automation.mark_light_manual(str(light_id))
        updated.append({"id": light_id, "bri": new_bri})
        # Per-light row in light_adjustments so Alexa "brighter"/"dimmer"
        # is visible in the same place as dashboard slider drags.
        await _log_light_change(
            request, str(light_id), light, {"bri": new_bri}, trigger=trigger,
        )

    return {
        "status": "ok",
        "direction": direction,
        "updated": updated,
        "ceiling": ceiling,
    }


@router.post("/all", dependencies=[Depends(require_api_key)])
async def set_all_lights(state: LightState, request: Request) -> dict:
    """Set the same state on all lights (used for scenes)."""
    hue = request.app.state.hue
    _check_hue_available(hue)

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
