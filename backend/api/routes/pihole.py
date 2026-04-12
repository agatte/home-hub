"""
Pi-hole endpoints — DNS ad blocking stats from a local Pi-hole instance.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.pihole")

router = APIRouter(prefix="/api/pihole", tags=["pihole"])


@router.get("/stats")
async def get_pihole_stats(request: Request) -> dict:
    """
    Get Pi-hole summary stats.

    Returns cached data (60s TTL) from the Pi-hole API.
    """
    service = getattr(request.app.state, "pihole_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Pi-hole service not configured — set PIHOLE_API_URL and PIHOLE_API_KEY in .env",
        )

    data = await service.get_summary()
    if not data:
        raise HTTPException(status_code=502, detail="Pi-hole data unavailable")

    return {"status": "ok", "pihole": data}


@router.get("/top-blocked")
async def get_top_blocked(request: Request, count: int = 10) -> dict:
    """
    Get the most frequently blocked domains.

    Returns cached data (120s TTL) from the Pi-hole API.
    """
    service = getattr(request.app.state, "pihole_service", None)
    if not service:
        raise HTTPException(
            status_code=503,
            detail="Pi-hole service not configured — set PIHOLE_API_URL and PIHOLE_API_KEY in .env",
        )

    data = await service.get_top_blocked(count=count)
    if data is None:
        raise HTTPException(status_code=502, detail="Pi-hole data unavailable")

    return {"status": "ok", "top_blocked": data}
