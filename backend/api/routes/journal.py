"""
Apartment Logbook routes — list/read/regenerate the nightly journal entries.

Read endpoints are unauthenticated (the dashboard is LAN-only and the
content is per-apartment narrative summary). The regenerate endpoint
mutates filesystem state, so it requires the API key like other write
routes.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.journal")

router = APIRouter(prefix="/api/journal", tags=["journal"])


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date '{value}' — expected YYYY-MM-DD",
        )


@router.get("/entries")
async def list_entries(request: Request) -> dict:
    """List all journal files, newest-first."""
    journal = getattr(request.app.state, "journal_service", None)
    if not journal:
        raise HTTPException(status_code=503, detail="Journal service not initialized")
    return {"entries": journal.list_entries()}


@router.get("/{entry_date}")
async def read_entry(entry_date: str, request: Request) -> dict:
    """Return raw markdown for a specific date (YYYY-MM-DD)."""
    journal = getattr(request.app.state, "journal_service", None)
    if not journal:
        raise HTTPException(status_code=503, detail="Journal service not initialized")
    d = _parse_date(entry_date)
    content = journal.read_entry(d)
    if content is None:
        raise HTTPException(status_code=404, detail=f"No entry for {entry_date}")
    return {"date": d.isoformat(), "markdown": content}


@router.post("/generate/{entry_date}", dependencies=[Depends(require_api_key)])
async def generate_entry(entry_date: str, request: Request) -> dict:
    """Force-regenerate the entry for a specific date (overwrites)."""
    journal = getattr(request.app.state, "journal_service", None)
    if not journal:
        raise HTTPException(status_code=503, detail="Journal service not initialized")
    d = _parse_date(entry_date)
    path = await journal.generate_for_date(d)
    return {
        "status": "ok",
        "date": d.isoformat(),
        "path": str(path),
    }
