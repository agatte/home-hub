"""
Weather endpoints — current conditions from the NWS API.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.weather")

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("")
async def get_weather(request: Request) -> dict:
    """
    Get current weather conditions.

    Returns cached data (5-minute TTL) from the NWS API.
    """
    service = getattr(request.app.state, "weather_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Weather service not configured",
        )

    data = await service.get_current()
    if not data:
        raise HTTPException(status_code=502, detail="Weather data unavailable")

    return {"status": "ok", "weather": data}


@router.get("/alerts")
async def get_weather_alerts(request: Request) -> dict:
    """Get active NWS weather alerts for Indianapolis."""
    service = getattr(request.app.state, "weather_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Weather service not configured",
        )

    alerts = await service.refresh_alerts()
    return {"status": "ok", "alerts": alerts}
