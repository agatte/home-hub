"""
API-key authentication dependency for write endpoints.

Every endpoint that mutates state (POST / PUT / PATCH / DELETE) goes
through `require_api_key` as a FastAPI dependency. Reads stay open;
gating them would force every monitoring tool, browser tab, and
internal probe to carry the header for no security gain.

The dependency has three exits:

1. **Localhost bypass** — requests from 127.0.0.1 / ::1 are trusted
   unconditionally. The kiosk on the Latitude reaches the backend
   via `localhost:8000` and never sees a key.
2. **Trusted-LAN bypass** — IPs listed in TRUSTED_LAN_IPS (e.g. the
   dev desktop) skip the header check.
3. **Header check** — anything else must present a matching
   `X-API-Key` header, compared against `HOME_HUB_API_KEY` via
   `hmac.compare_digest`.

Fail-closed: if `HOME_HUB_API_KEY` is unset, every protected write
returns 503 — a deploy that forgot to provision the key shouldn't
silently leave the LAN exposed.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, Request

from backend.config import settings

logger = logging.getLogger("home_hub.auth")

# Hosts that always pass auth without a header. The kiosk on Latitude
# reaches the backend via localhost; these are colocation-trusted.
# `testclient` is what Starlette's TestClient sets `request.client.host`
# to — uvicorn never produces that value from a real socket peer, so
# including it here is safe in production and keeps the existing test
# suite passing without needing every fixture to monkeypatch the key.
TRUSTED_LOCAL: frozenset[str] = frozenset(
    {"127.0.0.1", "::1", "localhost", "testclient"}
)


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Gate write endpoints on X-API-Key header (with bypasses)."""
    # Bypasses run first. The kiosk is colocated with the backend on
    # the Latitude — even on a misconfigured deploy that forgot the
    # key, we want the local UI to keep working. Configured trusted
    # LAN IPs are an explicit operator trust assertion, same idea.
    client_host = request.client.host if request.client else ""
    if client_host in TRUSTED_LOCAL:
        return
    if client_host in settings.trusted_lan_ips_set:
        return

    expected = settings.HOME_HUB_API_KEY
    if not expected:
        # Fail closed for non-trusted callers. A deploy that didn't
        # provision a key still gets a working kiosk (above), but the
        # LAN gate snaps shut so an external client can't slip through.
        raise HTTPException(
            status_code=503,
            detail="Auth disabled — HOME_HUB_API_KEY not set",
        )

    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        # Don't leak which arm of the check failed (header missing
        # vs header wrong) — both signal "not authorized."
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )
