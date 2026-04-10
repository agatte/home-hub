"""
Home Hub MCP Server — Claude Code integration.

Exposes the Home Hub REST API as MCP tools so Claude can verify changes
against the live system without manual testing. Requires the main Home Hub
server to be running at http://localhost:8000.

Usage:
    python -m backend.mcp_server

Registered in .claude/mcp.json as the "home-hub" MCP server.
"""
import logging
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
mcp = FastMCP("home-hub", instructions="Tools for inspecting and controlling the live Home Hub system. The main server must be running at http://localhost:8000.")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_health() -> dict:
    """Check system health — Hue bridge + Sonos connectivity and WebSocket client count."""
    async with _client() as c:
        r = await c.get("/health")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_weather() -> dict:
    """Get current weather conditions (temperature, description, humidity, wind)."""
    async with _client() as c:
        r = await c.get("/api/weather")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_lights() -> list[dict]:
    """Get the current state of all Hue lights (id, name, on, bri, hue, sat, reachable)."""
    async with _client() as c:
        r = await c.get("/api/lights")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def set_light(
    light_id: str,
    on: Optional[bool] = None,
    bri: Optional[int] = None,
    hue: Optional[int] = None,
    sat: Optional[int] = None,
) -> dict:
    """
    Set the state of a single Hue light.

    Args:
        light_id: Light ID (e.g. "1", "2", "3", "4")
        on: True to turn on, False to turn off
        bri: Brightness 1-254
        hue: Color hue 0-65535
        sat: Saturation 0-254
    """
    state: dict[str, Any] = {}
    if on is not None:
        state["on"] = on
    if bri is not None:
        state["bri"] = bri
    if hue is not None:
        state["hue"] = hue
    if sat is not None:
        state["sat"] = sat

    async with _client() as c:
        r = await c.put(f"/api/lights/{light_id}", json=state)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_automation_status() -> dict:
    """Get the current automation state: active mode, source, manual override status."""
    async with _client() as c:
        r = await c.get("/api/automation/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def set_mode(mode: str) -> dict:
    """
    Manually override the automation mode.

    Args:
        mode: One of gaming, watching, working, social, relax, movie, idle, away, sleeping.
              Use "auto" to clear the override and return to time-based automation.
    """
    async with _client() as c:
        r = await c.post("/api/automation/override", json={"mode": mode})
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_schedule() -> dict:
    """Get the current time-based lighting schedule (weekday and weekend periods)."""
    async with _client() as c:
        r = await c.get("/api/automation/schedule")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_mode_brightness() -> dict:
    """Get per-mode brightness multipliers (0.3-1.5 range per mode)."""
    async with _client() as c:
        r = await c.get("/api/automation/mode-brightness")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Screen sync
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_screen_sync_status() -> dict:
    """
    Get current screen sync state.

    Returns whether the mode gate is open (current mode is in
    gaming/watching/movie), when the last color was applied, what source
    posted it, and whether the laptop loopback is running.
    """
    async with _client() as c:
        r = await c.get("/api/automation/screen-sync/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def apply_screen_color(r: int, g: int, b: int) -> dict:
    """
    Manually post an RGB color to the screen sync receiver.

    Useful for testing — bypasses the desktop pc_agent. Will only update the
    bedroom lamp if the current automation mode is gaming, watching, or movie.

    Args:
        r: Red channel 0-255
        g: Green channel 0-255
        b: Blue channel 0-255
    """
    async with _client() as c:
        resp = await c.post(
            "/api/automation/screen-color",
            json={"r": r, "g": g, "b": b, "source": "mcp"},
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def set_laptop_screen_sync(enabled: bool) -> dict:
    """
    Toggle the in-process laptop screen capture loopback.

    This is the TV-on-laptop escape hatch. Default off; only flip on when
    the laptop is plugged into a TV and you want lights to follow it.

    Args:
        enabled: True to start the loopback, False to stop.
    """
    async with _client() as c:
        resp = await c.put(
            "/api/automation/screen-sync/laptop-enabled",
            json={"enabled": enabled},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Scenes & Effects
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_scenes() -> dict:
    """List all available scenes (built-in presets + native Hue bridge scenes)."""
    async with _client() as c:
        r = await c.get("/api/scenes")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def activate_scene(scene_id: str) -> dict:
    """
    Activate a scene by ID or preset name.

    Args:
        scene_id: Preset name (e.g. "movie_night", "relax") or Hue bridge scene UUID
    """
    async with _client() as c:
        r = await c.post(f"/api/scenes/{scene_id}/activate")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_effects() -> dict:
    """List available dynamic light effects (candlelight, fireplace, sparkle, etc.)."""
    async with _client() as c:
        r = await c.get("/api/scenes/effects")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def activate_effect(effect_name: str) -> dict:
    """
    Apply a dynamic effect to all lights.

    Args:
        effect_name: One of candle, fire, sparkle, prism, glisten, opal
    """
    async with _client() as c:
        r = await c.post(f"/api/scenes/effects/{effect_name}")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Sonos
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_sonos_status() -> dict:
    """Get current Sonos playback state (track, artist, volume, play state)."""
    async with _client() as c:
        r = await c.get("/api/sonos/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_play() -> dict:
    """Resume Sonos playback."""
    async with _client() as c:
        r = await c.post("/api/sonos/play")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_pause() -> dict:
    """Pause Sonos playback."""
    async with _client() as c:
        r = await c.post("/api/sonos/pause")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_volume(volume: int) -> dict:
    """
    Set Sonos volume.

    Args:
        volume: Volume level 0-100
    """
    async with _client() as c:
        r = await c.post("/api/sonos/volume", json={"volume": volume})
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_sonos_favorites() -> dict:
    """List all Sonos favorites and playlists."""
    async with _client() as c:
        r = await c.get("/api/sonos/favorites")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_mode_playlists() -> dict:
    """Get all mode-to-playlist mappings and available Sonos favorites."""
    async with _client() as c:
        r = await c.get("/api/music/mode-playlists")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Event summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_event_summary(days: int = 7) -> dict:
    """
    Summarize behavioral events over the last N days.

    Returns mode transition counts, most-adjusted lights, and most-played
    Sonos favorites. Useful for understanding usage patterns and debugging.

    Args:
        days: Number of days to look back (default 7).
    """
    import aiosqlite
    from datetime import datetime, timedelta, timezone

    from backend.config import DATA_DIR

    db_path = DATA_DIR / "home_hub.db"
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    result: dict = {"days": days, "mode_transitions": {}, "light_adjustments": [], "sonos_events": []}

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Mode transition counts
        async with db.execute(
            "SELECT mode, COUNT(*) as count FROM activity_events "
            "WHERE timestamp >= ? GROUP BY mode ORDER BY count DESC",
            (since,),
        ) as cursor:
            result["mode_transitions"] = {row["mode"]: row["count"] for row in await cursor.fetchall()}

        # Most-adjusted lights
        async with db.execute(
            "SELECT light_name, light_id, COUNT(*) as count FROM light_adjustments "
            "WHERE timestamp >= ? GROUP BY light_id ORDER BY count DESC LIMIT 5",
            (since,),
        ) as cursor:
            result["light_adjustments"] = [dict(row) for row in await cursor.fetchall()]

        # Most-played Sonos favorites
        async with db.execute(
            "SELECT favorite_title, event_type, COUNT(*) as count FROM sonos_playback_events "
            "WHERE timestamp >= ? AND favorite_title IS NOT NULL "
            "GROUP BY favorite_title, event_type ORDER BY count DESC LIMIT 10",
            (since,),
        ) as cursor:
            result["sonos_events"] = [dict(row) for row in await cursor.fetchall()]

    return result


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_routines() -> dict:
    """Get all routine configs (morning routine, evening wind-down)."""
    async with _client() as c:
        r = await c.get("/api/routines")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Database (read-only debug queries)
# ---------------------------------------------------------------------------


@mcp.tool()
async def query_db(sql: str) -> list[dict]:
    """
    Run a read-only SQL query against the Home Hub SQLite database.
    Only SELECT statements are permitted.

    Args:
        sql: A SELECT query, e.g. "SELECT * FROM mode_playlists"

    Returns:
        List of rows as dicts.

    Raises:
        ValueError: If the query is not a SELECT statement.
    """
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT"):
        raise ValueError("Only SELECT queries are permitted via this tool.")

    import aiosqlite

    from backend.config import DATA_DIR

    db_path = DATA_DIR / "home_hub.db"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


if __name__ == "__main__":
    mcp.run()
