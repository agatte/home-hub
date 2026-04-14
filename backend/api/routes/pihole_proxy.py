"""Reverse proxy for Pi-hole admin UI.

Strips X-Frame-Options / CSP headers so the dashboard can embed the
Pi-hole admin in an iframe.  Both the Home Hub backend and Pi-hole run
on the same machine (Latitude), so this is a localhost-to-localhost
proxy with negligible overhead.

Routes ``/admin/{path}`` and ``/api/{path}`` are registered AFTER all
Home Hub API routers, so our own ``/api/lights``, ``/api/pihole/stats``
etc. match first.  Only unmatched ``/api/*`` paths (which are Pi-hole's
own endpoints like ``/api/auth``) fall through to this proxy.
"""

import logging

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pihole-proxy"])

PIHOLE_ORIGIN = "http://localhost:8080"
_STRIP_RESPONSE = frozenset({
    "x-frame-options",
    "content-security-policy",
    "transfer-encoding",
})
_SKIP_REQUEST = frozenset({"host", "transfer-encoding"})


async def _proxy(request: Request, target_url: str) -> Response:
    """Forward *request* to *target_url*, stripping frame-blocking headers."""
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_REQUEST
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                follow_redirects=False,
            )
    except httpx.ConnectError:
        return Response(
            content=b"Pi-hole unreachable",
            status_code=502,
        )

    out_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _STRIP_RESPONSE
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=out_headers,
    )


_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]


@router.api_route("/admin/{path:path}", methods=_METHODS)
async def proxy_pihole_admin(path: str, request: Request) -> Response:
    """Proxy Pi-hole admin UI assets.

    Top-level document navigations (``Sec-Fetch-Dest: document``) are
    redirected back to the dashboard so the kiosk can't get stuck on the
    Pi-hole page after a session restore or direct URL entry.  Iframe
    loads (``Sec-Fetch-Dest: iframe``) and sub-resource fetches (style,
    script, image, etc.) are proxied normally.
    """
    if request.headers.get("sec-fetch-dest") == "document":
        return RedirectResponse("/")
    qs = f"?{request.query_params}" if request.query_params else ""
    return await _proxy(request, f"{PIHOLE_ORIGIN}/admin/{path}{qs}")


@router.api_route("/api/{path:path}", methods=_METHODS)
async def proxy_pihole_api(path: str, request: Request) -> Response:
    """Proxy Pi-hole API calls made from within the iframe.

    Only reached for ``/api/*`` paths that didn't match any Home Hub
    router (registered earlier).  Pi-hole uses ``/api/auth``,
    ``/api/stats``, ``/api/dns`` etc. which don't overlap with our
    ``/api/lights``, ``/api/pihole/*``, ``/api/sonos`` etc.
    """
    qs = f"?{request.query_params}" if request.query_params else ""
    return await _proxy(request, f"{PIHOLE_ORIGIN}/api/{path}{qs}")
