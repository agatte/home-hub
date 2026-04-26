"""Debug endpoints — read-only DB access for the home-hub MCP.

Powers the MCP `query_db` and `get_event_summary` tools. Lives behind
``/api/debug/`` so it's grouped with other operational utilities.

LAN-only by deployment. Two independent layers gate writes:

1. **Engine-level read-only**: the connection is opened with the
   SQLite URI ``file:...?mode=ro``. Every mutation attempt fails at
   the engine with ``SQLITE_READONLY`` regardless of what the SQL
   string contains. This is the load-bearing guarantee.
2. **Statement validator**: rejects anything whose first non-comment
   token isn't ``SELECT`` or ``WITH`` (CTE reads are legitimate). The
   validator is best-effort defense in depth — even if a future change
   widens it, the engine will still refuse to write.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException

from backend.config import DATA_DIR

router = APIRouter(prefix="/api/debug", tags=["debug"])

DB_PATH = DATA_DIR / "home_hub.db"

# SQLite supports a read-only open via URI mode. Forward slashes work
# on both POSIX and Windows; ``Path.as_posix()`` produces the right
# shape on both.
_RO_URI = f"file:{DB_PATH.as_posix()}?mode=ro"

# Cap how many rows a single /query call returns. Most diagnostic
# queries return a handful; this protects against accidentally
# `SELECT *` on a 100k-row event table from blowing memory.
MAX_QUERY_ROWS = 1000

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_ALLOWED_LEADING_TOKENS = {"SELECT", "WITH"}


def _is_read_only_query(sql: str) -> bool:
    """True if the first non-comment token is SELECT or WITH (CTE).

    Strips line (``--``) and block (``/* */``) comments before
    inspecting the leading token so a query starting with a comment
    isn't rejected. Defense in depth only — the engine connection is
    read-only regardless.
    """
    if not sql or not sql.strip():
        return False
    stripped = _BLOCK_COMMENT_RE.sub(" ", sql)
    stripped = _LINE_COMMENT_RE.sub(" ", stripped).strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0].upper()
    return first_token in _ALLOWED_LEADING_TOKENS


@router.get("/query")
async def query(sql: str) -> dict[str, Any]:
    """Run a SELECT-only SQL query against the live SQLite DB.

    Args:
        sql: A SELECT statement (CTEs starting with WITH are also
            accepted — they're read queries too).

    Returns:
        ``{"result": [row, ...], "truncated": bool}`` where each row
        is a column-name → value dict. Up to ``MAX_QUERY_ROWS`` are
        returned; larger result sets set ``truncated=True``.

    Raises:
        HTTPException 400 if the query isn't a read query.
    """
    if not _is_read_only_query(sql):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT (or WITH ... SELECT) queries are permitted",
        )

    async with aiosqlite.connect(_RO_URI, uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql) as cursor:
            # Pull MAX+1 to detect overflow without loading the whole table.
            rows = await cursor.fetchmany(MAX_QUERY_ROWS + 1)
            truncated = len(rows) > MAX_QUERY_ROWS
            return {
                "result": [dict(r) for r in rows[:MAX_QUERY_ROWS]],
                "truncated": truncated,
            }


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

    async with aiosqlite.connect(_RO_URI, uri=True) as db:
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
