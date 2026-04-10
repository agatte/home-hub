"""
Scene endpoints — curated presets, custom user scenes, bridge scenes, and effects.

Curated presets define per-light states for 15 well-designed lighting combos.
Custom scenes are user-created and persisted to SQLite.
Bridge scenes are native Hue scenes visible to Alexa / the Hue app.
Effects are real-time dynamic animations run by the bridge hardware.
"""
import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas.lights import CustomSceneCreate

logger = logging.getLogger("home_hub.scenes")

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

_OFF = {"on": False}


# ------------------------------------------------------------------
# 15 Curated Scene Presets (per-light states + category + effect)
# ------------------------------------------------------------------

SCENE_PRESETS: dict[str, dict[str, Any]] = {
    # === Functional (science-backed) ===
    "deep_focus": {
        "display_name": "Deep Focus",
        "category": "functional",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 254, "ct": 200},
            "2": {"on": True, "bri": 254, "ct": 200},
            "3": {"on": True, "bri": 254, "ct": 200},
            "4": {"on": True, "bri": 254, "ct": 200},
        },
    },
    "night_work": {
        "display_name": "Night Work",
        "category": "functional",
        "effect": "opal",
        "lights": {
            "1": _OFF,
            "2": {"on": True, "bri": 80, "ct": 370},
            "3": _OFF,
            "4": _OFF,
        },
    },
    "morning_energize": {
        "display_name": "Morning Energize",
        "category": "functional",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 254, "ct": 153},
            "2": {"on": True, "bri": 254, "ct": 153},
            "3": {"on": True, "bri": 254, "ct": 153},
            "4": {"on": True, "bri": 254, "ct": 153},
        },
    },
    "wind_down": {
        "display_name": "Wind Down",
        "category": "functional",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 40, "ct": 454},
            "2": {"on": True, "bri": 40, "ct": 454},
            "3": {"on": True, "bri": 40, "ct": 454},
            "4": {"on": True, "bri": 40, "ct": 454},
        },
    },

    # === Mood / Atmosphere (HSB colors) ===
    "sunset_glow": {
        "display_name": "Sunset Glow",
        "category": "mood",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 5000, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 2000, "sat": 254},
            "3": {"on": True, "bri": 160, "hue": 8000, "sat": 200},
            "4": {"on": True, "bri": 140, "hue": 3000, "sat": 254},
        },
    },
    "ocean_calm": {
        "display_name": "Ocean Calm",
        "category": "mood",
        "effect": "glisten",
        "lights": {
            "1": {"on": True, "bri": 150, "hue": 40000, "sat": 180},
            "2": {"on": True, "bri": 120, "hue": 46920, "sat": 200},
            "3": {"on": True, "bri": 140, "hue": 43000, "sat": 160},
            "4": {"on": True, "bri": 130, "hue": 46920, "sat": 180},
        },
    },
    "forest": {
        "display_name": "Forest",
        "category": "mood",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 160, "hue": 25500, "sat": 200},
            "2": {"on": True, "bri": 140, "hue": 22000, "sat": 180},
            "3": {"on": True, "bri": 120, "hue": 12750, "sat": 150},
            "4": {"on": True, "bri": 100, "hue": 25500, "sat": 220},
        },
    },
    "lava": {
        "display_name": "Lava",
        "category": "mood",
        "effect": "fire",
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 0, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 3000, "sat": 254},
            "3": {"on": True, "bri": 160, "hue": 5000, "sat": 254},
            "4": {"on": True, "bri": 200, "hue": 2000, "sat": 254},
        },
    },
    "arctic": {
        "display_name": "Arctic",
        "category": "mood",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 220, "hue": 40000, "sat": 80},
            "2": {"on": True, "bri": 200, "hue": 46920, "sat": 120},
            "3": {"on": True, "bri": 230, "ct": 153},
            "4": {"on": True, "bri": 180, "hue": 43000, "sat": 100},
        },
    },
    "twilight": {
        "display_name": "Twilight",
        "category": "mood",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 100, "hue": 50000, "sat": 220},
            "2": {"on": True, "bri": 80, "hue": 46920, "sat": 254},
            "3": {"on": True, "bri": 90, "hue": 54000, "sat": 200},
            "4": {"on": True, "bri": 70, "hue": 50000, "sat": 240},
        },
    },

    # === Entertainment ===
    "movie_night": {
        "display_name": "Movie Night",
        "category": "entertainment",
        "effect": None,
        "lights": {
            "1": _OFF,
            "2": {"on": True, "bri": 30, "ct": 400},
            "3": _OFF,
            "4": _OFF,
        },
    },
    "game_time": {
        "display_name": "Game Time",
        "category": "entertainment",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 150, "hue": 56100, "sat": 200},
            "2": {"on": True, "bri": 120, "ct": 300},
            "3": {"on": True, "bri": 130, "hue": 56100, "sat": 180},
            "4": {"on": True, "bri": 100, "hue": 46920, "sat": 200},
        },
    },

    # === Social ===
    "dinner_party": {
        "display_name": "Dinner Party",
        "category": "social",
        "effect": "candle",
        "lights": {
            "1": {"on": True, "bri": 150, "ct": 400},
            "2": {"on": True, "bri": 150, "ct": 400},
            "3": {"on": True, "bri": 120, "ct": 454},
            "4": {"on": True, "bri": 120, "ct": 454},
        },
    },
    "lounge": {
        "display_name": "Lounge",
        "category": "social",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 120, "hue": 50000, "sat": 150},
            "2": {"on": True, "bri": 100, "ct": 370},
            "3": {"on": True, "bri": 100, "hue": 54000, "sat": 120},
            "4": {"on": True, "bri": 80, "ct": 370},
        },
    },

    # === Special ===
    "candlelight": {
        "display_name": "Candlelight",
        "category": "special",
        "effect": "candle",
        "lights": {
            "1": {"on": True, "bri": 40, "ct": 500},
            "2": {"on": True, "bri": 40, "ct": 500},
            "3": {"on": True, "bri": 40, "ct": 500},
            "4": {"on": True, "bri": 40, "ct": 500},
        },
    },
}


# ------------------------------------------------------------------
# Scene list + activate
# ------------------------------------------------------------------


async def _activate_per_light(hue, light_states: dict, transitiontime: int = 10):
    """Apply per-light states to the bridge with a smooth transition."""
    tasks = []
    for lid, lstate in light_states.items():
        state_with_transition = {**lstate, "transitiontime": transitiontime}
        tasks.append(hue.set_light(lid, state_with_transition))
    await asyncio.gather(*tasks)


async def _activate_effect_if_needed(hue_v2, effect: str | None):
    """Activate or stop an effect if specified."""
    if not hue_v2 or not hue_v2.connected:
        return
    if effect:
        await hue_v2.set_effect_all(effect)
    else:
        await hue_v2.stop_effect_all()


@router.get("")
async def list_scenes(request: Request) -> dict:
    """
    List all available scenes — curated presets, custom user scenes, and bridge scenes.

    Each scene includes source ('preset', 'custom', 'bridge'), category, and effect.
    """
    # Curated presets
    presets = [
        {
            "id": name,
            "name": name,
            "display_name": data["display_name"],
            "category": data["category"],
            "effect": data.get("effect"),
            "source": "preset",
        }
        for name, data in SCENE_PRESETS.items()
    ]

    # Custom scenes from DB
    custom_scenes = []
    try:
        from sqlalchemy import select, text

        db = request.app.state.db
        async with db() as session:
            result = await session.execute(text("SELECT * FROM scenes ORDER BY name"))
            rows = result.fetchall()
            for row in rows:
                custom_scenes.append({
                    "id": f"custom_{row[0]}",
                    "name": row[1],
                    "display_name": row[1],
                    "category": row[3] if len(row) > 3 and row[3] else "custom",
                    "effect": row[4] if len(row) > 4 else None,
                    "source": "custom",
                })
    except Exception as e:
        logger.debug(f"No custom scenes or table not ready: {e}")

    # Native bridge scenes via v2 API
    bridge_scenes = []
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if hue_v2 and hue_v2.connected:
        try:
            bridge_scenes = await hue_v2.get_scenes()
        except Exception as e:
            logger.error(f"Error fetching bridge scenes: {e}")

    return {"scenes": presets + custom_scenes + bridge_scenes}


@router.post("/{scene_id}/activate")
async def activate_scene(scene_id: str, request: Request) -> dict:
    """
    Activate a scene by ID.

    Routes to curated preset, custom DB scene, or native bridge scene by ID type.
    """
    hue = request.app.state.hue
    hue_v2 = getattr(request.app.state, "hue_v2", None)
    ws_manager = request.app.state.ws_manager

    # Check curated preset
    if scene_id in SCENE_PRESETS:
        if not hue.connected:
            raise HTTPException(status_code=503, detail="Hue bridge not connected")

        preset = SCENE_PRESETS[scene_id]
        await _activate_per_light(hue, preset["lights"])
        await _activate_effect_if_needed(hue_v2, preset.get("effect"))

        await asyncio.sleep(0.3)
        lights = await hue.get_all_lights()
        for light in lights:
            await ws_manager.broadcast("light_update", light)

        return {"status": "ok", "scene": scene_id, "source": "preset"}

    # Check custom scene (custom_{id})
    if scene_id.startswith("custom_"):
        db_id = scene_id.removeprefix("custom_")
        try:
            from sqlalchemy import text

            db = request.app.state.db
            async with db() as session:
                result = await session.execute(
                    text("SELECT light_states, effect FROM scenes WHERE id = :id"),
                    {"id": int(db_id)},
                )
                row = result.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Custom scene not found")

                light_states = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                effect = row[1] if len(row) > 1 else None

                await _activate_per_light(hue, light_states)
                await _activate_effect_if_needed(hue_v2, effect)

                await asyncio.sleep(0.3)
                lights = await hue.get_all_lights()
                for light in lights:
                    await ws_manager.broadcast("light_update", light)

                return {"status": "ok", "scene": scene_id, "source": "custom"}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error activating custom scene: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Native bridge scene UUID
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

    await asyncio.sleep(0.5)
    lights = await hue.get_all_lights()
    for light in lights:
        await ws_manager.broadcast("light_update", light)

    return {"status": "ok", "scene": scene_id, "source": "bridge"}


# ------------------------------------------------------------------
# Custom scene CRUD
# ------------------------------------------------------------------


@router.post("/custom")
async def create_custom_scene(body: CustomSceneCreate, request: Request) -> dict:
    """Create a new custom scene."""
    from sqlalchemy import text

    db = request.app.state.db
    async with db() as session:
        result = await session.execute(
            text(
                "INSERT INTO scenes (name, light_states, category, effect) "
                "VALUES (:name, :light_states, :category, :effect)"
            ),
            {
                "name": body.name,
                "light_states": json.dumps(body.light_states),
                "category": body.category or "custom",
                "effect": body.effect,
            },
        )
        await session.commit()
        scene_id = result.lastrowid

    return {"status": "ok", "id": scene_id, "name": body.name}


@router.get("/custom")
async def list_custom_scenes(request: Request) -> dict:
    """List all custom user scenes."""
    from sqlalchemy import text

    db = request.app.state.db
    async with db() as session:
        result = await session.execute(text("SELECT * FROM scenes ORDER BY name"))
        rows = result.fetchall()

    scenes = []
    for row in rows:
        scenes.append({
            "id": row[0],
            "name": row[1],
            "light_states": json.loads(row[2]) if isinstance(row[2], str) else row[2],
            "category": row[3] if len(row) > 3 and row[3] else "custom",
            "effect": row[4] if len(row) > 4 else None,
            "source": "custom",
        })

    return {"scenes": scenes}


@router.put("/custom/{scene_id}")
async def update_custom_scene(
    scene_id: int, body: CustomSceneCreate, request: Request
) -> dict:
    """Update an existing custom scene."""
    from sqlalchemy import text

    db = request.app.state.db
    async with db() as session:
        result = await session.execute(
            text(
                "UPDATE scenes SET name = :name, light_states = :light_states, "
                "category = :category, effect = :effect WHERE id = :id"
            ),
            {
                "name": body.name,
                "light_states": json.dumps(body.light_states),
                "category": body.category or "custom",
                "effect": body.effect,
                "id": scene_id,
            },
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Scene not found")

    return {"status": "ok", "id": scene_id}


@router.delete("/custom/{scene_id}")
async def delete_custom_scene(scene_id: int, request: Request) -> dict:
    """Delete a custom scene."""
    from sqlalchemy import text

    db = request.app.state.db
    async with db() as session:
        result = await session.execute(
            text("DELETE FROM scenes WHERE id = :id"), {"id": scene_id}
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Scene not found")

    return {"status": "ok"}


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
