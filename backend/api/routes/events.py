"""
Event query endpoints — read-only access to behavioral event data.

Provides aggregation, pattern detection, and paginated history for the
learning engine, analytics dashboard, and nudge system.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request

logger = logging.getLogger("home_hub.events")

router = APIRouter(prefix="/api/events", tags=["events"])


def _get_service(request: Request):
    """Get EventQueryService from app state."""
    return request.app.state.event_query_service


@router.get("/summary")
async def get_summary(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    """High-level stats across all event tables for a time window."""
    service = _get_service(request)
    return await service.get_summary(days)


@router.get("/activity")
async def get_activity(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    mode: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated activity event history with optional filters."""
    service = _get_service(request)
    return await service.get_activity(days=days, mode=mode, source=source, limit=limit, offset=offset)


@router.get("/patterns")
async def get_patterns(request: Request, days: int = Query(30, ge=7, le=90)) -> dict:
    """Time-based pattern analysis for the rule engine."""
    service = _get_service(request)
    return await service.get_patterns(days)


@router.get("/timeline")
async def get_timeline(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    """Mode timeline for visualization."""
    service = _get_service(request)
    events = await service.get_timeline(days)
    return {"events": events}


@router.get("/lights")
async def get_light_events(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    light_id: Optional[str] = None,
    trigger: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated light adjustment history."""
    service = _get_service(request)
    return await service.get_light_events(days=days, light_id=light_id, trigger=trigger, limit=limit, offset=offset)


@router.get("/sonos")
async def get_sonos_events(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    event_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated Sonos event history."""
    service = _get_service(request)
    return await service.get_sonos_events(days=days, event_type=event_type, limit=limit, offset=offset)
