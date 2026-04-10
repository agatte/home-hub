"""
Weather endpoints — current conditions from OpenWeatherMap.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.weather")

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("")
async def get_weather(request: Request) -> dict:
    """
    Get current weather conditions.

    Returns cached data (10-minute TTL) from OpenWeatherMap.
    """
    service = getattr(request.app.state, "weather_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Weather service not configured — set OPENWEATHER_API_KEY in .env",
        )

    data = await service.get_current()
    if not data:
        raise HTTPException(status_code=502, detail="Weather data unavailable")

    return {"status": "ok", "weather": data}
