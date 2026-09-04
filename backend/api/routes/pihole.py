"""
Pi-hole endpoints — DNS ad blocking stats, local DNS, and blocklist management.
"""
import logging
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key
from backend.services.pihole_service import PiholeUnreachableError

logger = logging.getLogger("home_hub.pihole")

router = APIRouter(prefix="/api/pihole", tags=["pihole"])

NOT_CONFIGURED = "Pi-hole service not configured — set PIHOLE_API_URL and PIHOLE_API_KEY in .env"
UNREACHABLE_DETAIL = "Pi-hole unreachable"


def _get_service(request: Request):
    """Get Pi-hole service or raise 503."""
    service = getattr(request.app.state, "pihole_service", None)
    if not service:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return service


def _unreachable(err: PiholeUnreachableError) -> HTTPException:
    """Map a service-layer unreachable error to a 503 with cause detail."""
    return HTTPException(
        status_code=503,
        detail=f"{UNREACHABLE_DETAIL}: {err}",
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_pihole_stats(request: Request) -> dict:
    """Get Pi-hole summary stats (60s cache)."""
    service = _get_service(request)
    try:
        data = await service.get_summary()
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    if not data:
        raise HTTPException(status_code=502, detail="Pi-hole data unavailable")
    return {"status": "ok", "pihole": data}


@router.get("/top-blocked")
async def get_top_blocked(request: Request, count: int = 10) -> dict:
    """Get the most frequently blocked domains (120s cache)."""
    service = _get_service(request)
    try:
        data = await service.get_top_blocked(count=count)
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
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
    try:
        data = await service.get_dns_hosts()
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok", "dns_hosts": data}


@router.post("/dns", dependencies=[Depends(require_api_key)])
async def add_dns_host(body: DnsHostBody, request: Request) -> dict:
    """Add a local DNS record."""
    service = _get_service(request)
    try:
        await service.add_dns_host(body.ip, body.hostname)
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}


@router.delete("/dns/{ip}/{hostname}", dependencies=[Depends(require_api_key)])
async def delete_dns_host(ip: str, hostname: str, request: Request) -> dict:
    """Remove a local DNS record."""
    service = _get_service(request)
    try:
        await service.delete_dns_host(ip, hostname)
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
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
    try:
        data = await service.get_blocklists()
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok", "lists": data}


@router.post("/lists", dependencies=[Depends(require_api_key)])
async def add_blocklist(body: BlocklistBody, request: Request) -> dict:
    """Add a blocklist URL."""
    service = _get_service(request)
    try:
        await service.add_blocklist(body.address)
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}


@router.delete("/lists/{address:path}", dependencies=[Depends(require_api_key)])
async def delete_blocklist(address: str, request: Request) -> dict:
    """Remove a blocklist by URL."""
    service = _get_service(request)
    try:
        await service.delete_blocklist(unquote(address))
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}


@router.post("/gravity", dependencies=[Depends(require_api_key)])
async def refresh_gravity(request: Request) -> dict:
    """Refresh all configured Pi-hole lists and rebuild gravity."""
    service = _get_service(request)
    try:
        await service.refresh_gravity()
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Allowlist (exact-domain exceptions)
# ---------------------------------------------------------------------------


class AllowDomainBody(BaseModel):
    domain: str
    comment: Optional[str] = None


@router.get("/allow")
async def get_allow_domains(request: Request) -> dict:
    """List all exact-allow (whitelisted) domains."""
    service = _get_service(request)
    try:
        data = await service.get_allow_domains()
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok", "allow": data}


@router.post("/allow", dependencies=[Depends(require_api_key)])
async def add_allow_domain(body: AllowDomainBody, request: Request) -> dict:
    """Whitelist a single domain (un-block a false positive)."""
    service = _get_service(request)
    try:
        await service.add_allow_domain(body.domain, body.comment)
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}


@router.delete("/allow/{domain:path}", dependencies=[Depends(require_api_key)])
async def delete_allow_domain(domain: str, request: Request) -> dict:
    """Remove a domain from the allowlist."""
    service = _get_service(request)
    try:
        await service.delete_allow_domain(unquote(domain))
    except PiholeUnreachableError as e:
        raise _unreachable(e) from e
    return {"status": "ok"}
