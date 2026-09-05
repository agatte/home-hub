"""
Bar app integration endpoints — status summary from Home Bar app.
"""
import logging
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.bar")

router = APIRouter(prefix="/api/bar", tags=["bar"])


def _browser_bar_url(request: Request, app_url: str) -> str:
    """Translate a loopback-only configured URL into the browser's HomeHub host."""
    parsed = urlsplit(app_url)
    if (parsed.hostname or "").lower() not in {"localhost", "127.0.0.1", "::1"}:
        return app_url

    browser_host = request.url.hostname
    if not browser_host:
        return app_url
    host = f"[{browser_host}]" if ":" in browser_host else browser_host
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


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
        "bar_app_url": _browser_bar_url(request, service.app_url),
    }
