"""
Scene endpoints — curated presets, custom user scenes, bridge scenes, and effects.

Curated presets define per-light states for 20 well-designed lighting combos
using color harmony theory (analogous, complementary, split-complementary).
Custom scenes are user-created and persisted to SQLite.
Bridge scenes are native Hue scenes visible to Alexa / the Hue app.
Effects are real-time dynamic animations run by the bridge hardware.
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas.lights import CustomSceneCreate
from backend.database import async_session

logger = logging.getLogger("home_hub.scenes")

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

_OFF = {"on": False}


# ------------------------------------------------------------------
# 20 Curated Scene Presets
# Color harmony: analogous (adjacent hues), complementary (opposing),
# split-complementary, triadic. Brightness + saturation vary per light
# to create depth. Effects paired only when they enhance the scene.
#
# Lights: L1=living room corner, L2=bedroom desk lamp,
#         L3=kitchen front, L4=kitchen back
# ------------------------------------------------------------------

SCENE_PRESETS: dict[str, dict[str, Any]] = {

    # ===================== FUNCTIONAL =====================

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
        "effect": None,
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

    # ===================== COZY & WARM =====================
    # Analogous warm palette — adjacent hues on warm side of wheel

    "golden_hour": {
        "display_name": "Golden Hour",
        "category": "cozy",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 180, "hue": 7000, "sat": 220},
            "2": {"on": True, "bri": 160, "hue": 5000, "sat": 180},
            "3": {"on": True, "bri": 120, "hue": 8500, "sat": 200},
            "4": {"on": True, "bri": 100, "hue": 6000, "sat": 254},
        },
    },
    "ember": {
        "display_name": "Ember",
        "category": "cozy",
        "effect": "fire",
        "lights": {
            "1": {"on": True, "bri": 140, "hue": 1500, "sat": 254},
            "2": {"on": True, "bri": 100, "hue": 0, "sat": 240},
            "3": {"on": True, "bri": 80, "hue": 3000, "sat": 254},
            "4": {"on": True, "bri": 120, "hue": 500, "sat": 254},
        },
    },
    "candlelit": {
        "display_name": "Candlelit",
        "category": "cozy",
        "effect": "candle",
        "lights": {
            "1": {"on": True, "bri": 50, "ct": 500},
            "2": {"on": True, "bri": 50, "ct": 500},
            "3": {"on": True, "bri": 50, "ct": 500},
            "4": {"on": True, "bri": 50, "ct": 500},
        },
    },

    # ===================== MOODY & DRAMATIC =====================
    # Complementary + deep saturation, low brightness for drama

    "noir": {
        "display_name": "Noir",
        "category": "moody",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 60, "hue": 46920, "sat": 254},
            "2": {"on": True, "bri": 100, "hue": 7000, "sat": 200},
            "3": {"on": True, "bri": 40, "hue": 50000, "sat": 220},
            "4": {"on": True, "bri": 50, "hue": 48000, "sat": 240},
        },
    },
    "midnight": {
        "display_name": "Midnight",
        "category": "moody",
        "effect": "glisten",
        "lights": {
            "1": {"on": True, "bri": 80, "hue": 48000, "sat": 254},
            "2": {"on": True, "bri": 60, "hue": 52000, "sat": 200},
            "3": {"on": True, "bri": 50, "hue": 46920, "sat": 220},
            "4": {"on": True, "bri": 40, "hue": 50000, "sat": 240},
        },
    },
    "blood_moon": {
        "display_name": "Blood Moon",
        "category": "moody",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 120, "hue": 0, "sat": 254},
            "2": {"on": True, "bri": 80, "hue": 36000, "sat": 200},
            "3": {"on": True, "bri": 60, "hue": 1000, "sat": 254},
            "4": {"on": True, "bri": 50, "hue": 34000, "sat": 180},
        },
    },

    # ===================== VIBRANT & ENERGETIC =====================
    # Triadic + split-complementary, high saturation, bold

    "neon_tokyo": {
        "display_name": "Neon Tokyo",
        "category": "vibrant",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 56100, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 46920, "sat": 254},
            "3": {"on": True, "bri": 160, "hue": 52000, "sat": 254},
            "4": {"on": True, "bri": 140, "hue": 60000, "sat": 240},
        },
    },
    "arcade": {
        "display_name": "Arcade",
        "category": "vibrant",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 25500, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 50000, "sat": 254},
            "3": {"on": True, "bri": 160, "hue": 36000, "sat": 254},
            "4": {"on": True, "bri": 120, "hue": 25500, "sat": 220},
        },
    },
    "miami_vice": {
        "display_name": "Miami Vice",
        "category": "vibrant",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 60000, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 36000, "sat": 220},
            "3": {"on": True, "bri": 140, "hue": 58000, "sat": 240},
            "4": {"on": True, "bri": 120, "hue": 34000, "sat": 200},
        },
    },

    # ===================== NATURE-INSPIRED =====================
    # Analogous palettes drawn from natural phenomena

    "northern_lights": {
        "display_name": "Northern Lights",
        "category": "nature",
        "effect": "glisten",
        "lights": {
            "1": {"on": True, "bri": 160, "hue": 25500, "sat": 220},
            "2": {"on": True, "bri": 140, "hue": 34000, "sat": 200},
            "3": {"on": True, "bri": 100, "hue": 50000, "sat": 180},
            "4": {"on": True, "bri": 120, "hue": 28000, "sat": 240},
        },
    },
    "sunset_strip": {
        "display_name": "Sunset Strip",
        "category": "nature",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 200, "hue": 0, "sat": 254},
            "2": {"on": True, "bri": 180, "hue": 5000, "sat": 254},
            "3": {"on": True, "bri": 140, "hue": 60000, "sat": 200},
            "4": {"on": True, "bri": 100, "hue": 52000, "sat": 180},
        },
    },
    "deep_ocean": {
        "display_name": "Deep Ocean",
        "category": "nature",
        "effect": "glisten",
        "lights": {
            "1": {"on": True, "bri": 100, "hue": 46920, "sat": 254},
            "2": {"on": True, "bri": 120, "hue": 38000, "sat": 200},
            "3": {"on": True, "bri": 80, "hue": 44000, "sat": 220},
            "4": {"on": True, "bri": 60, "hue": 30000, "sat": 180},
        },
    },
    "cherry_blossom": {
        "display_name": "Cherry Blossom",
        "category": "nature",
        "effect": None,
        "lights": {
            "1": {"on": True, "bri": 180, "hue": 58000, "sat": 140},
            "2": {"on": True, "bri": 160, "ct": 300},
            "3": {"on": True, "bri": 140, "hue": 52000, "sat": 100},
            "4": {"on": True, "bri": 120, "hue": 60000, "sat": 160},
        },
    },

    # ===================== ENTERTAINMENT =====================

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
            "1": {"on": True, "bri": 150, "hue": 50000, "sat": 200},
            "2": {"on": True, "bri": 120, "hue": 46920, "sat": 180},
            "3": {"on": True, "bri": 100, "hue": 52000, "sat": 160},
            "4": {"on": True, "bri": 80, "hue": 46920, "sat": 200},
        },
    },

    # ===================== SOCIAL =====================

    "house_party": {
        "display_name": "House Party",
        "category": "social",
        "effect": "prism",
        "lights": {
            "1": {"on": True, "bri": 254, "hue": 0, "sat": 254},
            "2": {"on": True, "bri": 254, "hue": 25500, "sat": 254},
            "3": {"on": True, "bri": 254, "hue": 46920, "sat": 254},
            "4": {"on": True, "bri": 254, "hue": 56100, "sat": 254},
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
    """Activate a paired effect if specified. Does nothing if no effect."""
    if not hue_v2 or not hue_v2.connected:
        return
    if effect:
        await hue_v2.set_effect_all(effect)


@router.get("")
async def list_scenes(request: Request) -> dict:
    """
    List all available scenes — curated presets, custom user scenes, and bridge scenes.

    Each scene includes source ('preset', 'custom', 'bridge'), category, and effect.
    """
    # Curated presets — include per-light states for frontend preview
    presets = [
        {
            "id": name,
            "name": name,
            "display_name": data["display_name"],
            "category": data["category"],
            "effect": data.get("effect"),
            "source": "preset",
            "lights": data.get("lights"),
        }
        for name, data in SCENE_PRESETS.items()
    ]

    # Custom scenes from DB — include per-light states for frontend preview
    custom_scenes = []
    try:
        from sqlalchemy import text

        async with async_session() as session:
            result = await session.execute(text("SELECT * FROM scenes ORDER BY name"))
            rows = result.fetchall()
            for row in rows:
                light_states = (
                    json.loads(row[2]) if isinstance(row[2], str) else row[2]
                )
                custom_scenes.append({
                    "id": f"custom_{row[0]}",
                    "name": row[1],
                    "display_name": row[1],
                    "category": row[3] if len(row) > 3 and row[3] else "custom",
                    "effect": row[4] if len(row) > 4 else None,
                    "source": "custom",
                    "lights": light_states,
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


async def _log_scene_activation(
    request: Request, scene_id: str, scene_name: Optional[str], source: str
) -> None:
    """Fire-and-forget scene activation log entry."""
    event_logger = getattr(request.app.state, "event_logger", None)
    automation = getattr(request.app.state, "automation", None)
    if event_logger:
        mode_at_time = automation.current_mode if automation else None
        await event_logger.log_scene_activation(
            scene_id=scene_id,
            scene_name=scene_name,
            source=source,
            mode_at_time=mode_at_time,
        )


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

        # Apply light states first — setting explicit hue/sat/bri or ct
        # automatically cancels any running effect on that light, so we
        # don't need a separate stop_effect_all (which causes a visible
        # flash as the bridge snaps to a raw state before our transition).
        await _activate_per_light(hue, preset["lights"])

        # Then apply paired effect if the scene has one
        await _activate_effect_if_needed(hue_v2, preset.get("effect"))

        await asyncio.sleep(0.3)
        lights = await hue.get_all_lights()
        for light in lights:
            await ws_manager.broadcast("light_update", light)

        await _log_scene_activation(
            request, scene_id, preset.get("display_name"), "preset"
        )
        return {"status": "ok", "scene": scene_id, "source": "preset"}

    # Check custom scene (custom_{id})
    if scene_id.startswith("custom_"):
        db_id = scene_id.removeprefix("custom_")
        try:
            from sqlalchemy import text

            async with async_session() as session:
                result = await session.execute(
                    text("SELECT name, light_states, effect FROM scenes WHERE id = :id"),
                    {"id": int(db_id)},
                )
                row = result.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Custom scene not found")

                scene_name = row[0]
                light_states = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                effect = row[2] if len(row) > 2 else None

                await _activate_per_light(hue, light_states)
                await _activate_effect_if_needed(hue_v2, effect)

                await asyncio.sleep(0.3)
                lights = await hue.get_all_lights()
                for light in lights:
                    await ws_manager.broadcast("light_update", light)

                await _log_scene_activation(request, scene_id, scene_name, "custom")
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

    await _log_scene_activation(request, scene_id, None, "bridge")
    return {"status": "ok", "scene": scene_id, "source": "bridge"}


# ------------------------------------------------------------------
# Custom scene CRUD
# ------------------------------------------------------------------


@router.post("/custom")
async def create_custom_scene(body: CustomSceneCreate, request: Request) -> dict:
    """Create a new custom scene."""
    from sqlalchemy import text

    async with async_session() as session:
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

    async with async_session() as session:
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

    async with async_session() as session:
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

    async with async_session() as session:
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


# ------------------------------------------------------------------
# "Try It" — activate a scene temporarily and auto-revert
# ------------------------------------------------------------------

# Single-slot: only one trial can be active at a time.
_try_it_state: dict[str, Any] = {
    "task": None,
    "snapshot": None,
    "snapshot_id": None,
}


async def _revert_after_delay(
    hue: Any, ws_manager: Any, snapshot: list[dict], delay: int
) -> None:
    """Wait *delay* seconds, then restore the snapshot light states."""
    try:
        await asyncio.sleep(delay)
        for light in snapshot:
            state: dict[str, Any] = {}
            if light.get("on") is not None:
                state["on"] = light["on"]
            if light.get("bri") is not None:
                state["bri"] = light["bri"]
            if light.get("colormode") == "ct" and light.get("ct"):
                state["ct"] = light["ct"]
            elif light.get("hue") is not None and light.get("sat") is not None:
                state["hue"] = light["hue"]
                state["sat"] = light["sat"]
            state["transitiontime"] = 10  # 1s smooth revert
            await hue.set_light(light["light_id"], state)
        await asyncio.sleep(0.3)
        lights = await hue.get_all_lights()
        for light in lights:
            await ws_manager.broadcast("light_update", light)
    except asyncio.CancelledError:
        pass  # cancelled by a new trial or explicit cancel
    except Exception as e:
        logger.error("Try-it revert failed: %s", e, exc_info=True)
    finally:
        _try_it_state["task"] = None
        _try_it_state["snapshot"] = None
        _try_it_state["snapshot_id"] = None


@router.post("/try/cancel")
async def cancel_try(request: Request) -> dict:
    """
    Cancel an active scene trial and immediately revert to the snapshot.
    """
    hue = request.app.state.hue
    ws_manager = request.app.state.ws_manager

    if not _try_it_state["task"] or _try_it_state["task"].done():
        return {"status": "ok", "detail": "No active trial"}

    # Cancel the delayed revert
    _try_it_state["task"].cancel()
    snapshot = _try_it_state["snapshot"]

    if snapshot:
        # Immediately revert
        for light in snapshot:
            state: dict[str, Any] = {}
            if light.get("on") is not None:
                state["on"] = light["on"]
            if light.get("bri") is not None:
                state["bri"] = light["bri"]
            if light.get("colormode") == "ct" and light.get("ct"):
                state["ct"] = light["ct"]
            elif light.get("hue") is not None and light.get("sat") is not None:
                state["hue"] = light["hue"]
                state["sat"] = light["sat"]
            state["transitiontime"] = 5  # 0.5s quick revert
            await hue.set_light(light["light_id"], state)
        await asyncio.sleep(0.3)
        lights = await hue.get_all_lights()
        for light in lights:
            await ws_manager.broadcast("light_update", light)

    _try_it_state["task"] = None
    _try_it_state["snapshot"] = None
    _try_it_state["snapshot_id"] = None

    return {"status": "reverted"}


@router.post("/{scene_id}/try")
async def try_scene(scene_id: str, request: Request) -> dict:
    """
    Activate a scene temporarily for 30 seconds, then auto-revert.

    Snapshots the current light states, activates the requested scene,
    and schedules a revert task. Only one trial can be active at a time.
    """
    hue = request.app.state.hue
    ws_manager = request.app.state.ws_manager

    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    # Cancel any existing trial
    if _try_it_state["task"] and not _try_it_state["task"].done():
        _try_it_state["task"].cancel()

    # Snapshot current light states
    snapshot = await hue.get_all_lights()

    # Activate the scene using the existing activate logic
    result = await activate_scene(scene_id, request)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail="Scene activation failed")

    # Schedule revert
    sid = str(uuid.uuid4())[:8]
    task = asyncio.create_task(
        _revert_after_delay(hue, ws_manager, snapshot, 30)
    )
    _try_it_state["task"] = task
    _try_it_state["snapshot"] = snapshot
    _try_it_state["snapshot_id"] = sid

    return {"status": "ok", "revert_after": 30, "snapshot_id": sid}
