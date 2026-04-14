"""
Bar app integration endpoints — status summary from Home Bar app.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.bar")

router = APIRouter(prefix="/api/bar", tags=["bar"])


@router.get("/status")
async def get_bar_status(request: Request) -> dict:
    """
    Get bar status from the Home Bar app.

    Returns cached data (10-minute TTL) with inventory summary,
    party mode state, and cocktail suggestion.
    """
    service = getattr(request.app.state, "bar_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Bar app not configured — set BAR_APP_URL in .env",
        )

    data = await service.get_status()
    if not data:
        raise HTTPException(status_code=502, detail="Bar app data unavailable")

    return {
        "status": "ok",
        "bar_summary": data,
        "bar_app_url": service.app_url,
    }
