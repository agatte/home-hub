"""
Pi-hole endpoints — DNS ad blocking stats, local DNS, and blocklist management.
"""
import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.pihole")

router = APIRouter(prefix="/api/pihole", tags=["pihole"])

NOT_CONFIGURED = "Pi-hole service not configured — set PIHOLE_API_URL and PIHOLE_API_KEY in .env"


def _get_service(request: Request):
    """Get Pi-hole service or raise 503."""
    service = getattr(request.app.state, "pihole_service", None)
    if not service:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return service


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_pihole_stats(request: Request) -> dict:
    """Get Pi-hole summary stats (60s cache)."""
    service = _get_service(request)
    data = await service.get_summary()
    if not data:
        raise HTTPException(status_code=502, detail="Pi-hole data unavailable")
    return {"status": "ok", "pihole": data}


@router.get("/top-blocked")
async def get_top_blocked(request: Request, count: int = 10) -> dict:
    """Get the most frequently blocked domains (120s cache)."""
    service = _get_service(request)
    data = await service.get_top_blocked(count=count)
    if data is None:
        raise HTTPException(status_code=502, detail="Pi-hole data unavailable")
    return {"status": "ok", "top_blocked": data}


# ---------------------------------------------------------------------------
# Local DNS
# ---------------------------------------------------------------------------


class DnsHostBody(BaseModel):
    ip: str
    hostname: str


@router.get("/dns")
async def get_dns_hosts(request: Request) -> dict:
    """List all custom local DNS records."""
    service = _get_service(request)
    data = await service.get_dns_hosts()
    if data is None:
        raise HTTPException(status_code=502, detail="Pi-hole DNS data unavailable")
    return {"status": "ok", "dns_hosts": data}


@router.post("/dns", dependencies=[Depends(require_api_key)])
async def add_dns_host(body: DnsHostBody, request: Request) -> dict:
    """Add a local DNS record."""
    service = _get_service(request)
    ok = await service.add_dns_host(body.ip, body.hostname)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to add DNS record")
    return {"status": "ok"}


@router.delete("/dns/{ip}/{hostname}", dependencies=[Depends(require_api_key)])
async def delete_dns_host(ip: str, hostname: str, request: Request) -> dict:
    """Remove a local DNS record."""
    service = _get_service(request)
    ok = await service.delete_dns_host(ip, hostname)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to delete DNS record")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Blocklists
# ---------------------------------------------------------------------------


class BlocklistBody(BaseModel):
    address: str


@router.get("/lists")
async def get_blocklists(request: Request) -> dict:
    """List all configured adlists."""
    service = _get_service(request)
    data = await service.get_blocklists()
    if data is None:
        raise HTTPException(status_code=502, detail="Pi-hole blocklist data unavailable")
    return {"status": "ok", "lists": data}


@router.post("/lists", dependencies=[Depends(require_api_key)])
async def add_blocklist(body: BlocklistBody, request: Request) -> dict:
    """Add a blocklist URL."""
    service = _get_service(request)
    ok = await service.add_blocklist(body.address)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to add blocklist")
    return {"status": "ok"}


@router.delete("/lists/{address:path}", dependencies=[Depends(require_api_key)])
async def delete_blocklist(address: str, request: Request) -> dict:
    """Remove a blocklist by URL."""
    service = _get_service(request)
    ok = await service.delete_blocklist(unquote(address))
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to delete blocklist")
    return {"status": "ok"}
