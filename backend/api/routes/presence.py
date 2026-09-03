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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.auth import require_api_key, require_localhost, source_from_request
from backend.services.away_manager import (
    HomeReconciliationIndeterminate,
    HomeReconciliationRejected,
)

logger = logging.getLogger("home_hub.api.presence")

router = APIRouter(prefix="/api/presence", tags=["presence"])


class GeofenceEvent(BaseModel):
    event: Literal["leave", "arrive"]


class HomeReconciliationRequest(BaseModel):
    reconciliation_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


@router.post("/geofence", dependencies=[Depends(require_api_key)])
async def geofence_event(payload: GeofenceEvent, request: Request) -> dict:
    """Handle an iOS Shortcut geofence leave/arrive event."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    source = source_from_request(request, fallback="ios_shortcut")
    logger.info("Geofence webhook: event=%s source=%s", payload.event, source)
    return await away_manager.handle_event(payload.event, source)


@router.post("/reconcile-home", dependencies=[Depends(require_localhost)])
async def reconcile_home(
    payload: HomeReconciliationRequest,
    request: Request,
) -> dict:
    """Strict localhost-only commit boundary for Latitude Return Home."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    source = source_from_request(request, fallback="return_home:hostctl")
    try:
        result = await away_manager.reconcile_home(
            source=source,
            reconciliation_id=payload.reconciliation_id,
        )
    except HomeReconciliationRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"outcome": "definitive_failure", "message": str(exc)},
        ) from exc
    except HomeReconciliationIndeterminate as exc:
        raise HTTPException(
            status_code=503,
            detail={"outcome": "indeterminate", "message": str(exc)},
        ) from exc

    return result


@router.post(
    "/reconcile-home/{reconciliation_id}/activate",
    dependencies=[Depends(require_localhost)],
)
async def activate_home_reconciliation(
    reconciliation_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Release RETURNING_HOME suppression after hostctl durably publishes HOME."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    source = source_from_request(request, fallback="return_home:hostctl")
    try:
        result = await away_manager.activate_home_reconciliation(
            source=source,
            reconciliation_id=reconciliation_id,
        )
    except HomeReconciliationRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"outcome": "definitive_failure", "message": str(exc)},
        ) from exc
    except HomeReconciliationIndeterminate as exc:
        raise HTTPException(
            status_code=503,
            detail={"outcome": "indeterminate", "message": str(exc)},
        ) from exc
    if result.pop("effects_required"):
        background_tasks.add_task(
            away_manager.run_arrival_effects,
            source=source,
            away_minutes=result.pop("away_minutes"),
        )
    else:
        result.pop("away_minutes")
    return result


@router.get(
    "/reconcile-home/{reconciliation_id}",
    dependencies=[Depends(require_localhost)],
)
async def home_reconciliation_status(
    reconciliation_id: str,
    request: Request,
) -> dict:
    """Resolve a lost/timeout response using durable transaction identity."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    try:
        result = await away_manager.reconciliation_status(reconciliation_id)
    except HomeReconciliationIndeterminate as exc:
        raise HTTPException(
            status_code=503,
            detail={"outcome": "indeterminate", "message": str(exc)},
        ) from exc
    if not result["resolved"]:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/status")
async def presence_status(request: Request) -> dict:
    """Current away/home state (+ whether run_loop suppression is armed)."""
    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is None:
        raise HTTPException(status_code=503, detail="Away manager not ready")
    return away_manager.status()
