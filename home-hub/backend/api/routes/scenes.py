"""
Scene endpoints — built-in presets, native Hue bridge scenes, and dynamic effects.

Presets are hardcoded light states managed by Home Hub. Native scenes are stored
on the Hue bridge and visible to Alexa / the Hue app. Effects are real-time
dynamic animations (candlelight, fireplace, etc.) run by the bridge hardware.
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.scenes")

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

# Built-in scene presets: name -> Hue light state
SCENE_PRESETS: dict[str, dict[str, Any]] = {
    "movie_night": {
        "on": True,
        "bri": 50,
        "hue": 8000,
        "sat": 200,
    },
    "bright": {
        "on": True,
        "bri": 254,
        "hue": 8000,
        "sat": 140,
    },
    "colts_blue": {
        "on": True,
        "bri": 254,
        "hue": 46920,
        "sat": 254,
    },
    "relax": {
        "on": True,
        "bri": 120,
        "hue": 8000,
        "sat": 180,
    },
    "all_off": {
        "on": False,
    },
    "warm_white": {
        "on": True,
        "bri": 200,
        "hue": 8000,
        "sat": 140,
    },
    "daylight": {
        "on": True,
        "bri": 254,
        "hue": 34000,
        "sat": 50,
    },
}


@router.get("")
async def list_scenes(request: Request) -> dict:
    """
    List all available scenes — both built-in presets and native bridge scenes.

    Each scene includes a 'source' field: 'preset' for Home Hub presets,
    'bridge' for native Hue scenes (visible to Alexa).
    """
    # Built-in presets
    presets = [
        {
            "id": name,
            "name": name,
            "display_name": name.replace("_", " ").title(),
            "source": "preset",
        }
        for name in SCENE_PRESETS
    ]

    # Native bridge scenes via v2 API
    bridge_scenes = []
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if hue_v2 and hue_v2.connected:
        try:
            bridge_scenes = await hue_v2.get_scenes()
        except Exception as e:
            logger.error(f"Error fetching bridge scenes: {e}")

    return {"scenes": presets + bridge_scenes}


@router.post("/{scene_id}/activate")
async def activate_scene(scene_id: str, request: Request) -> dict:
    """
    Activate a scene by ID.

    If scene_id matches a preset name, applies the preset via v1 API.
    If scene_id is a UUID, activates the native bridge scene via v2 API.
    """
    hue = request.app.state.hue
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    ws_manager = request.app.state.ws_manager

    # Check if it's a built-in preset
    if scene_id in SCENE_PRESETS:
        if not hue.connected:
            raise HTTPException(status_code=503, detail="Hue bridge not connected")

        state = SCENE_PRESETS[scene_id]
        success = await hue.set_all_lights(state)

        # Broadcast light updates
        lights = await hue.get_all_lights()
        for light in lights:
            await ws_manager.broadcast("light_update", light)

        return {"status": "ok" if success else "partial_failure", "scene": scene_id}

    # Otherwise treat as a native bridge scene UUID
    if not hue_v2 or not hue_v2.connected:
        raise HTTPException(
            status_code=503,
            detail="Hue v2 API not connected — cannot activate native scene",
        )

    success = await hue_v2.activate_scene(scene_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Scene '{scene_id}' not found or activation failed",
        )

    # Broadcast updated light states (bridge scene changes take a moment)
    import asyncio
    await asyncio.sleep(0.5)
    lights = await hue.get_all_lights()
    for light in lights:
        await ws_manager.broadcast("light_update", light)

    return {"status": "ok", "scene": scene_id, "source": "bridge"}


# ------------------------------------------------------------------
# Dynamic effects
# ------------------------------------------------------------------

@router.get("/effects")
async def list_effects(request: Request) -> dict:
    """List available dynamic light effects (candlelight, fireplace, etc.)."""
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if not hue_v2 or not hue_v2.connected:
        return {"effects": [], "available": False}

    effects = await hue_v2.get_effects()
    return {"effects": effects, "available": True}


@router.post("/effects/{effect_name}")
async def activate_effect(effect_name: str, request: Request) -> dict:
    """
    Activate a dynamic effect on all lights.

    Valid effects: candle, fire, sparkle, prism, glisten, opal.
    Use effect_name 'stop' to stop all effects.
    """
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if not hue_v2 or not hue_v2.connected:
        raise HTTPException(
            status_code=503,
            detail="Hue v2 API not connected — cannot control effects",
        )

    if effect_name == "stop":
        success = await hue_v2.stop_effect_all()
        return {"status": "ok" if success else "partial_failure", "effect": "stopped"}

    valid_effects = {e["name"] for e in await hue_v2.get_effects()}
    if effect_name not in valid_effects:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown effect '{effect_name}'. "
            f"Available: {', '.join(sorted(valid_effects))}",
        )

    success = await hue_v2.set_effect_all(effect_name)
    return {"status": "ok" if success else "partial_failure", "effect": effect_name}


@router.post("/effects/{effect_name}/light/{light_id}")
async def activate_effect_on_light(
    effect_name: str, light_id: str, request: Request
) -> dict:
    """Activate a dynamic effect on a specific light (by v1 ID)."""
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if not hue_v2 or not hue_v2.connected:
        raise HTTPException(
            status_code=503,
            detail="Hue v2 API not connected",
        )

    if effect_name == "stop":
        success = await hue_v2.stop_effect(light_id)
    else:
        success = await hue_v2.set_effect(light_id, effect_name)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to set effect '{effect_name}' on light {light_id}",
        )

    return {"status": "ok", "effect": effect_name, "light_id": light_id}
