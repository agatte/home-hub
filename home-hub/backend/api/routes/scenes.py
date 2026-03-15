"""
Scene preset endpoints — one-tap light configurations.
"""
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

# Built-in scene presets: name -> Hue light state
SCENE_PRESETS: dict[str, dict] = {
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
async def list_scenes() -> dict:
    """List all available scene presets."""
    return {
        "scenes": [
            {"name": name, "display_name": name.replace("_", " ").title()}
            for name in SCENE_PRESETS
        ]
    }


@router.post("/{scene_name}/activate")
async def activate_scene(scene_name: str, request: Request) -> dict:
    """Activate a scene preset — sets all lights to the scene's configuration."""
    if scene_name not in SCENE_PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"Scene '{scene_name}' not found. "
            f"Available: {', '.join(SCENE_PRESETS.keys())}",
        )

    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    state = SCENE_PRESETS[scene_name]
    success = await hue.set_all_lights(state)

    # Broadcast light updates
    ws_manager = request.app.state.ws_manager
    lights = await hue.get_all_lights()
    for light in lights:
        await ws_manager.broadcast("light_update", light)

    return {"status": "ok" if success else "partial_failure", "scene": scene_name}
