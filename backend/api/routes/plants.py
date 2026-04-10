"""
Plant app integration endpoints — status summary from external plant care app.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.plants")

router = APIRouter(prefix="/api/plants", tags=["plants"])


@router.get("/status")
async def get_plant_status(request: Request) -> dict:
    """
    Get aggregated plant status from the plant care app.

    Returns cached data (10-minute TTL) with total count,
    needs-water count, overdue count, and next watering info.
    """
    service = getattr(request.app.state, "plant_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Plant app not configured — set PLANT_APP_* in .env",
        )

    data = await service.get_status()
    if not data:
        raise HTTPException(status_code=502, detail="Plant app data unavailable")

    return {"status": "ok", "plant_summary": data}
