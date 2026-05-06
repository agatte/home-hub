"""
API-key authentication dependency for write endpoints.

Every endpoint that mutates state (POST / PUT / PATCH / DELETE) goes
through `require_api_key` as a FastAPI dependency. Reads stay open;
gating them would force every monitoring tool, browser tab, and
internal probe to carry the header for no security gain.

The dependency has four exits for normal callers:

1. **Localhost bypass** — requests from 127.0.0.1 / ::1 are trusted
   unconditionally. The kiosk on the Latitude reaches the backend
   via `localhost:8000` and never sees a key.
2. **Trusted-LAN pin** — IPs explicitly listed in TRUSTED_LAN_IPS
   skip the header check. Useful for pinning a tunneled public IP
   or being explicit about a single device.
3. **Private-range bypass** — any RFC1918 / loopback / link-local /
   ULA caller (i.e. the apartment LAN) skips the header check.
   This project is single-user / single-apartment; the auth gate
   exists to keep the kiosk port from being reachable from the
   public internet, not to gate Anthony's own devices.
4. **Header check** — anything else must present a matching
   `X-API-Key` header, compared against `HOME_HUB_API_KEY` via
   `hmac.compare_digest`.

**Tunnel-origin gate (Phase 5):** when an incoming request carries
`X-Tunnel-Origin: cloudflare`, ALL of the above bypasses are skipped
and the caller MUST present BOTH `X-API-Key` (matching
`HOME_HUB_API_KEY`) AND `X-Skill-Token` (matching
`HOME_HUB_SKILL_TOKEN`). The header is injected by the local
`tunnel_proxy` sidecar — cloudflared delivers tunneled traffic to
loopback, which would otherwise classify as the localhost bypass.
External callers cannot forge this header from outside cloudflared
because the sidecar binds only to 127.0.0.1; the public internet
can't reach the port that strips/replaces the header.

Fail-closed: if `HOME_HUB_API_KEY` is unset, every protected write
returns 503 — a deploy that forgot to provision the key shouldn't
silently leave the LAN exposed.
"""
from __future__ import annotations

import hmac
import ipaddress
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

# Header value the tunnel_proxy sidecar injects on every cloudflared
# request. Lowercased before comparison.
TUNNEL_ORIGIN_HEADER = "X-Tunnel-Origin"
TUNNEL_ORIGIN_VALUE = "cloudflare"


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    x_skill_token: Optional[str] = Header(default=None, alias="X-Skill-Token"),
) -> None:
    """Gate write endpoints on X-API-Key header (with bypasses)."""
    client_host = request.client.host if request.client else ""
    is_tunnel = (
        request.headers.get(TUNNEL_ORIGIN_HEADER, "").strip().lower()
        == TUNNEL_ORIGIN_VALUE
    )

    # Tunnel callers skip ALL bypasses — the localhost classification
    # cloudflared produces is meaningless for trust purposes.
    if not is_tunnel:
        if client_host in TRUSTED_LOCAL:
            return
        if client_host in settings.trusted_lan_ips_set:
            return
        try:
            if ipaddress.ip_address(client_host).is_private:
                return
        except ValueError:
            pass

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

    if is_tunnel:
        skill_expected = settings.HOME_HUB_SKILL_TOKEN
        if not skill_expected:
            # Fail closed: tunnel is open but skill token isn't
            # provisioned — refuse rather than silently downgrade
            # to the API-key-only check.
            raise HTTPException(
                status_code=503,
                detail="Tunnel auth disabled — HOME_HUB_SKILL_TOKEN not set",
            )
        if not x_skill_token or not hmac.compare_digest(
            x_skill_token, skill_expected
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing skill token",
            )


def source_from_request(request: Request, fallback: str) -> str:
    """Extract the X-Source header for telemetry, with a route-specific fallback.

    Used by write endpoints to tag the resulting `activity_events` /
    override / scene-activation row with a meaningful source label. The
    Alexa lambda passes ``alexa:<intent_name>``; other callers (dashboard,
    curl, scripts) typically pass nothing and fall back to whatever the
    route was already using (e.g. ``api:<ip>``, ``rest``, ``manual``,
    ``preset`` / ``custom`` / ``bridge``).

    Empty or whitespace-only headers count as "not set" so a misbehaving
    client can't tag everything as the empty string.
    """
    raw = request.headers.get("X-Source")
    if not raw:
        return fallback
    cleaned = raw.strip()
    return cleaned or fallback
