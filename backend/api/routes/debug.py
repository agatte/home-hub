"""Debug endpoints — read-only DB access for the home-hub MCP.

Powers the MCP `query_db` and `get_event_summary` tools. Lives behind
``/api/debug/`` so it's grouped with other operational utilities.

LAN-only by deployment (no auth on this server in general). The
SELECT-only validator below provides defense in depth so a typo in the
MCP layer can't accidentally mutate state.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException

from backend.config import DATA_DIR

router = APIRouter(prefix="/api/debug", tags=["debug"])

DB_PATH = DATA_DIR / "home_hub.db"


@router.get("/query")
async def query(sql: str) -> dict[str, list[dict[str, Any]]]:
    """Run a SELECT-only SQL query against the live SQLite DB.

    Args:
        sql: A SELECT statement.

    Returns:
        ``{"result": [row, row, ...]}`` where each row is a column-name → value dict.

    Raises:
        HTTPException 400 if the query isn't a SELECT.
    """
    if not sql.strip().upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are permitted")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            return {"result": [dict(row) for row in rows]}


@router.get("/event-summary")
async def event_summary(days: int = 7) -> dict[str, Any]:
    """Aggregate behavioral events over the last N days.

    Returns mode-transition counts, top 5 most-adjusted lights, and
    top 10 most-played Sonos favorites. Used for understanding usage
    patterns and debugging from Claude Code.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result: dict[str, Any] = {
        "days": days,
        "mode_transitions": {},
        "light_adjustments": [],
        "sonos_events": [],
    }

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT mode, COUNT(*) AS count FROM activity_events "
            "WHERE timestamp >= ? GROUP BY mode ORDER BY count DESC",
            (since,),
        ) as cursor:
            result["mode_transitions"] = {
                row["mode"]: row["count"] for row in await cursor.fetchall()
            }

        async with db.execute(
            "SELECT light_name, light_id, COUNT(*) AS count FROM light_adjustments "
            "WHERE timestamp >= ? GROUP BY light_id ORDER BY count DESC LIMIT 5",
            (since,),
        ) as cursor:
            result["light_adjustments"] = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            "SELECT favorite_title, event_type, COUNT(*) AS count FROM sonos_playback_events "
            "WHERE timestamp >= ? AND favorite_title IS NOT NULL "
            "GROUP BY favorite_title, event_type ORDER BY count DESC LIMIT 10",
            (since,),
        ) as cursor:
            result["sonos_events"] = [dict(row) for row in await cursor.fetchall()]

    return result
