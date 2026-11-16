"""
Hue light control endpoints.
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from backend.api._guards import _check_hue_available
from backend.api.auth import require_api_key, source_from_request
from backend.api.schemas.lights import LightResponse, LightState
from backend.services.light_state_calculator import ALL_LIGHT_IDS
from backend.services.ws_manual_light_guard import dispatch_manual_light

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lights", tags=["lights"])

# Relative brightness step (multiplicative). Mirrors the guest endpoint —
# 10% per tap, floor of 20 units so taps stay perceptible at low bri.
_BRIGHTNESS_STEP = 1.10
_BRIGHTNESS_MIN_STEP = 20


@router.post("/{light_id}/hue-app-hold", dependencies=[Depends(require_api_key)])
async def hold_for_hue_app(light_id: str, request: Request) -> dict:
    """Reserve a manual slot; no Hue write. Four-hour/mode-change expiry applies."""
    _check_hue_available(request.app.state.hue)
    automation = getattr(request.app.state, "automation", None)
    if automation is None:
        raise HTTPException(503, "Automation unavailable")
    return await automation.hue_app_hold(light_id)


@router.delete("/{light_id}/hue-app-hold", dependencies=[Depends(require_api_key)])
async def release_hue_app_hold(
    light_id: str, request: Request,
    stamp: str = Body(embed=True, min_length=1, max_length=64),
) -> dict:
    """Release only the exact returned stamp; normal reconciliation resumes."""
    automation = getattr(request.app.state, "automation", None)
    if automation is None:
        raise HTTPException(503, "Automation unavailable")
    return await automation.hue_app_hold(light_id, expected_stamp=stamp)


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
    """Adjust one bulb under the same final-write authority as WebSocket.

    A transport acknowledgement does not establish physical readback.
    """
    hue = request.app.state.hue
    _check_hue_available(hue)

    if light_id not in ALL_LIGHT_IDS:
        raise HTTPException(status_code=404, detail="Unknown fixture")
    state_dict = state.model_dump(exclude_none=True)
    if not state_dict:
        raise HTTPException(status_code=400, detail="No state values provided")
    if "ct" in state_dict and ("hue" in state_dict or "sat" in state_dict):
        raise HTTPException(status_code=422, detail="CT and HSB cannot be mixed")

    # The API caller cannot mint a lease or claim a stronger owner's light.
    # This guard checks the shared serial boundary and final Hue worker fence,
    # then stamps/persists manual ownership only after a bridge transport ACK.
    automation = getattr(request.app.state, "automation", None)
    result = await dispatch_manual_light(automation, hue, light_id, state_dict)
    if result.status == "denied":
        raise HTTPException(status_code=409, detail="Lighting owner or lifecycle conflict")
    if result.status == "unavailable":
        raise HTTPException(status_code=503, detail="Lighting control unavailable")
    if result.status != "acknowledged":
        # The bridge could have applied some or all of this request. Using a
        # conflict response discourages generic 5xx retry middleware.
        raise HTTPException(
            status_code=409,
            detail="Lighting outcome uncertain; inspect the bulb before retrying",
        )

    # No post-write broadcast — the bridge is mid-transition and a fresh
    # read returns an intermediate value. Polling broadcasts after the
    # in-flight window (hue_service.poll_state_loop) and the frontend
    # optimistically patched its local store on the way in.

    try:
        await _log_light_change(
            request, light_id, result.before, state_dict,
            trigger=source_from_request(request, fallback="rest"),
        )
    except Exception:
        # Analytics failure cannot turn an acknowledged bridge mutation into
        # a misleading error that might invite another physical command.
        logger.warning("REST light adjustment event log unavailable")
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
    if automation is None:
        raise HTTPException(status_code=503, detail="Lighting authority unavailable")
    mode_mult = automation._mode_brightness.get(automation.current_mode, 1.0)
    ceiling = max(1, min(254, int(254 * mode_mult)))

    sign = 1 if direction == "up" else -1
    multiplicative_delta = _BRIGHTNESS_STEP - 1.0
    trigger = source_from_request(request, fallback="brightness_step")

    lights = await hue.get_all_lights()
    updated: list[dict] = []
    blocked: list[str] = []
    unavailable: list[str] = []
    uncertain: list[str] = []
    for light in lights:
        if not light.get("on") or "bri" not in light:
            continue
        current = light["bri"]
        delta = max(_BRIGHTNESS_MIN_STEP, round(current * multiplicative_delta))
        new_bri = max(1, min(ceiling, current + sign * delta))
        if new_bri == current:
            continue
        light_id = str(light["light_id"])
        result = await dispatch_manual_light(
            automation, hue, light_id, {"bri": new_bri},
        )
        if result.status != "acknowledged":
            if result.status == "denied":
                blocked.append(light_id)
            elif result.status == "unavailable":
                unavailable.append(light_id)
            else:
                # An ambiguous bridge ACK could mean partial physical change.
                # Never retry such a fixture automatically.
                uncertain.append(light_id)
            continue
        updated.append({"id": light_id, "bri": new_bri})
        try:
            await _log_light_change(
                request, light_id, result.before, {"bri": new_bri},
                trigger=trigger,
            )
        except Exception:
            logger.warning("REST brightness adjustment event log unavailable")

    return {
        "status": "partial_failure" if blocked or unavailable or uncertain else "ok",
        "direction": direction,
        "updated": updated,
        "blocked": blocked,
        "unavailable": unavailable,
        "uncertain": uncertain,
        "ceiling": ceiling,
    }


@router.post("/all", dependencies=[Depends(require_api_key)])
async def set_all_lights(state: LightState, request: Request) -> dict:
    """Explicit group manual action; every fixture must keep its own owner.

    No multi-light Hue dispatch or optimistic post-write broadcast: grouped
    outcomes can be partial and never prove physical bulb completion.
    """
    hue = request.app.state.hue
    _check_hue_available(hue)

    state_dict = state.model_dump(exclude_none=True)
    if not state_dict:
        raise HTTPException(status_code=400, detail="No state values provided")
    if "ct" in state_dict and ("hue" in state_dict or "sat" in state_dict):
        raise HTTPException(status_code=422, detail="CT and HSB cannot be mixed")
    automation = getattr(request.app.state, "automation", None)
    if automation is None:
        raise HTTPException(status_code=503, detail="Lighting authority unavailable")

    lights = await hue.get_all_lights()
    if not lights:
        raise HTTPException(status_code=503, detail="Lighting inventory unavailable")

    updated: list[str] = []
    blocked: list[str] = []
    unavailable: list[str] = []
    uncertain: list[str] = []
    seen: set[str] = set()
    for light in lights:
        light_id = str(light.get("light_id", ""))
        if light_id in seen:
            continue
        seen.add(light_id)
        if light_id not in ALL_LIGHT_IDS:
            # Never let newly discovered bridge fixtures join a bulk action
            # without deliberate HomeHub fixture inventory authorization.
            unavailable.append(light_id)
            continue
        result = await dispatch_manual_light(
            automation, hue, light_id, state_dict,
        )
        if result.status != "acknowledged":
            if result.status == "denied":
                blocked.append(light_id)
            elif result.status == "unavailable":
                unavailable.append(light_id)
            else:
                uncertain.append(light_id)
            continue

        updated.append(light_id)
        try:
            await _log_light_change(
                request, light_id, result.before, state_dict,
                trigger="all_lights",
            )
        except Exception:
            logger.warning("REST bulk light adjustment event log unavailable")

    # Explicit per-fixture status rather than a false all-or-nothing ACK.
    # A partially applied action is never automatically retried/rolled back.
    return {
        "status": "partial_failure" if blocked or unavailable or uncertain else "ok",
        "updated": updated,
        "blocked": blocked,
        "unavailable": unavailable,
        "uncertain": uncertain,
    }
