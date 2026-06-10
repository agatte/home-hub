"""
Presence routes — the iOS Shortcut geofence webhook + away-state read.

``POST /api/presence/geofence`` is the D2 entry point (GH#107): two iOS
Shortcuts automations ("When I leave home" / "When I arrive home") POST
``{"event": "leave"|"arrive"}`` here. The phone is on cellular when
geofences fire (leave: already walked out of WiFi range; arrive: still
~100m out), so the request rides the public Cloudflare tunnel →
``tunnel_proxy`` (allowlisted there) → strict tunnel auth in
``require_api_key`` (X-API-Key + X-Skill-Token, no LAN bypasses).
LAN/localhost callers keep the normal bypass — handy for testing.

The actual behaviors live in ``backend/services/away_manager.py``.
"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key, source_from_request

logger = logging.getLogger("home_hub.api.presence")

router = APIRouter(prefix="/api/presence", tags=["presence"])


class GeofenceEvent(BaseModel):
    event: Literal["leave", "arrive"]


@router.post("/geofence", dependencies=[Depends(require_api_key)])
async def geofence_event(payload: GeofenceEvent, request: Request) -> dict:
    """Handle an iOS Shortcut geofence leave/arrive event."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    source = source_from_request(request, fallback="ios_shortcut")
    logger.info("Geofence webhook: event=%s source=%s", payload.event, source)
    return await away_manager.handle_event(payload.event, source)


@router.get("/status")
async def presence_status(request: Request) -> dict:
    """Current away/home state (+ whether run_loop suppression is armed)."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    return away_manager.status()
