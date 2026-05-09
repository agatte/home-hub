"""
Analytics digest routes — surface the analytics-narrator agent's output.

The agent writes interpretive daily-narrative markdown to
``data/analytics/daily/YYYY-MM-DD.md``; this route lets the dashboard fetch
those files. There is no `generate` endpoint — generation is owned by the
agent (Claude Code), not the backend.

Read endpoints are unauthenticated (LAN-only dashboard, per-apartment
narrative). The same convention as ``backend/api/routes/journal.py``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from backend.config import PROJECT_ROOT

logger = logging.getLogger("home_hub.analytics")

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

TZ = ZoneInfo("America/Indiana/Indianapolis")
DIGEST_DIR = PROJECT_ROOT / "data" / "analytics" / "daily"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date '{value}' — expected YYYY-MM-DD",
        )


def _entry_meta(path: Path) -> dict[str, Any] | None:
    try:
        d = datetime.strptime(path.stem, "%Y-%m-%d").date()
    except ValueError:
        return None
    stat = path.stat()
    return {
        "date": d.isoformat(),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc,
        ).isoformat(),
    }


@router.get("/digest/entries")
async def list_entries() -> dict:
    """List every daily narrative file, newest first."""
    if not DIGEST_DIR.exists():
        return {"entries": []}
    out: list[dict[str, Any]] = []
    for p in sorted(DIGEST_DIR.glob("*.md"), reverse=True):
        meta = _entry_meta(p)
        if meta is not None:
            out.append(meta)
    return {"entries": out}


@router.get("/digest/daily")
async def latest_daily() -> dict:
    """
    Return the most recent narrative — what the analytics page shows.

    Falls back gracefully when nothing has been generated yet so the page
    can render an empty-state hint instead of erroring.
    """
    today = datetime.now(tz=TZ).date()
    yesterday = today - timedelta(days=1)

    # Prefer yesterday (the canonical daily-glance read), then today
    # (an in-progress narrative if the user just ran `/analytics-narrator today`),
    # then the newest file on disk for any older day.
    for candidate in (yesterday, today):
        path = DIGEST_DIR / f"{candidate.isoformat()}.md"
        if path.exists():
            return {
                "date": candidate.isoformat(),
                "markdown": path.read_text(encoding="utf-8"),
                "is_today": candidate == today,
            }

    if DIGEST_DIR.exists():
        candidates = sorted(DIGEST_DIR.glob("*.md"), reverse=True)
        if candidates:
            path = candidates[0]
            try:
                d = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                d = None
            return {
                "date": d.isoformat() if d else None,
                "markdown": path.read_text(encoding="utf-8"),
                "is_today": False,
            }

    return {"date": None, "markdown": "", "is_today": False}


@router.get("/digest/{entry_date}")
async def read_entry(entry_date: str) -> dict:
    """Return the narrative markdown for a specific date (YYYY-MM-DD)."""
    d = _parse_date(entry_date)
    path = DIGEST_DIR / f"{d.isoformat()}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No narrative for {entry_date}")
    return {"date": d.isoformat(), "markdown": path.read_text(encoding="utf-8")}
