"""
Cloudflare Tunnel passthrough — Phase 5 Custom Alexa Skill.

Cloudflared delivers external (tunneled) traffic to loopback, which would
otherwise classify as the localhost bypass in `require_api_key`. To
distinguish "tunneled from the public internet" from "kiosk on the same
machine," cloudflared is pointed at THIS proxy on 127.0.0.1:8002 instead
of the main app on 127.0.0.1:8000. The proxy:

1. Enforces an explicit `(method, path)` allowlist matching exactly the
   surface the Alexa Lambda calls. Anything else returns 404 — the public
   tunnel must NOT be a wildcard pipe into every backend route.
2. Adds `X-Tunnel-Origin: cloudflare` to every forwarded request — the
   marker that triggers the strict tunnel-auth path in
   `backend.api.auth.require_api_key` (require X-API-Key + X-Skill-Token,
   skip all bypasses).
3. Forwards the request to 127.0.0.1:8000 via httpx and streams the
   response back.

Run as a separate uvicorn process — keeps the proxy's lifecycle decoupled
from the main app and makes it impossible for an in-process bug to leak
the injection.

Binding: 127.0.0.1:8002 only. Cloudflared is local; nothing else needs
to reach this port. If a stray client on the LAN tried to inject a
forged `X-Tunnel-Origin` directly to :8000, the LAN bypass would fire
before reaching the gate — but the LAN can't reach :8002 because we
never bind it externally.

**Allowlist contract:** the regexes below MUST stay in sync with the
endpoints `alexa_skill/lambda_function.py` actually calls. Adding a new
Alexa intent without updating this file silently breaks that intent
through the tunnel. The constant values (mode/scene/effect literals) are
duplicated from the Lambda by design — the proxy is a separate process
and shouldn't import Lambda code or backend internals.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from backend.api.auth import TUNNEL_ORIGIN_HEADER, TUNNEL_ORIGIN_VALUE

logger = logging.getLogger("home_hub.tunnel_proxy")

UPSTREAM = "http://127.0.0.1:8000"

# Hop-by-hop headers that must NOT be forwarded (RFC 7230 §6.1) — a few
# of these (Connection, Transfer-Encoding) confuse httpx + uvicorn if
# blindly passed through, and Host gets rewritten to point at the upstream.
_DROP_REQUEST_HEADERS = frozenset({
    "connection", "host", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
    "content-length",  # httpx recomputes this from the body
})
_DROP_RESPONSE_HEADERS = frozenset({
    "connection", "keep-alive", "transfer-encoding", "upgrade",
    "content-encoding", "content-length",  # let starlette set these
})


# --- Allowlist of (method, path-regex) pairs the tunnel will forward.
#
# Every regex is anchored with ^...$. The path the proxy sees has a
# leading slash (we prepend it before matching). Wildcard segments are
# bounded enums — never `.*` — so a future Lambda bug can't surprise the
# tunnel into forwarding something exotic.
_SCENE_IDS = "(house_party|neon_tokyo|miami_vice|arcade|northern_lights|sunset_strip)"
_EFFECTS = "(candle|fire|sparkle|prism|glisten|opal)"
_DIR = "(up|down)"

_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = (
    # public liveness probe — minimal {"ok": true}, no internal state
    # leak. /health stays unallowlisted on purpose.
    ("GET", re.compile(r"^/api/ping$")),
    # automation
    ("POST", re.compile(r"^/api/automation/override$")),
    ("POST", re.compile(r"^/api/automation/dnd$")),
    ("DELETE", re.compile(r"^/api/automation/dnd$")),
    ("GET", re.compile(r"^/api/automation/status$")),
    # lights — brightness up/down only; no per-bulb POSTs over the tunnel
    ("POST", re.compile(rf"^/api/lights/brightness/{_DIR}$")),
    # scenes
    ("POST", re.compile(rf"^/api/scenes/{_SCENE_IDS}/activate$")),
    ("POST", re.compile(rf"^/api/scenes/effects/{_EFFECTS}$")),
    ("POST", re.compile(r"^/api/scenes/effects/stop$")),
    # sonos
    ("POST", re.compile(r"^/api/sonos/smart-play$")),
    ("POST", re.compile(r"^/api/sonos/pause$")),
    ("POST", re.compile(r"^/api/sonos/next$")),
    ("POST", re.compile(r"^/api/sonos/previous$")),
    ("POST", re.compile(rf"^/api/sonos/volume/{_DIR}$")),
    ("GET", re.compile(r"^/api/sonos/status$")),
)


def _is_allowed(method: str, full_path: str) -> bool:
    """Return True iff (method, full_path) matches an allowlist entry."""
    for allowed_method, pattern in _ALLOWED:
        if method == allowed_method and pattern.match(full_path):
            return True
    return False


def create_app() -> FastAPI:
    app = FastAPI(title="HomeHub Tunnel Proxy", docs_url=None, redoc_url=None)

    @app.on_event("startup")
    async def _startup() -> None:
        # Long timeout: the Skill expects the upstream call to complete
        # within Alexa's 8s budget anyway, so 6s is plenty without
        # cutting off legitimate slow ops (TTS generation, scene apply).
        app.state.client = httpx.AsyncClient(base_url=UPSTREAM, timeout=6.0)
        logger.info(
            "Tunnel proxy started — forwarding to %s (%d allowlist rules)",
            UPSTREAM, len(_ALLOWED),
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        client: httpx.AsyncClient = app.state.client
        await client.aclose()

    @app.api_route(
        "/{path:path}",
        # Only the methods the Lambda actually uses. HEAD/OPTIONS/PATCH/PUT
        # are intentionally absent — narrower surface, easier to reason about.
        methods=["GET", "POST", "DELETE"],
    )
    async def proxy(path: str, request: Request) -> Response:
        client: httpx.AsyncClient = request.app.state.client
        full_path = "/" + path

        if not _is_allowed(request.method, full_path):
            # 404 (not 403) — don't leak that the proxy exists or that
            # specific paths would be reachable with the right method.
            logger.info(
                "tunnel REJECT %s %s (not in allowlist)",
                request.method, full_path,
            )
            return Response(status_code=404, content=b"not found")

        # Strip hop-by-hop + force-set the tunnel marker. Also drop any
        # caller-supplied X-Tunnel-Origin (case-insensitive) so a forged
        # header can't slip through next to our injected one.
        forwarded_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in _DROP_REQUEST_HEADERS
            and k.lower() != TUNNEL_ORIGIN_HEADER.lower()
        }
        forwarded_headers[TUNNEL_ORIGIN_HEADER] = TUNNEL_ORIGIN_VALUE

        body = await request.body()
        url = full_path
        if request.url.query:
            url = f"{url}?{request.url.query}"

        try:
            upstream = await client.request(
                request.method,
                url,
                headers=forwarded_headers,
                content=body,
            )
        except httpx.ConnectError as exc:
            logger.error("Upstream connection refused: %s", exc)
            return Response(status_code=502, content=b"upstream unreachable")
        except httpx.TimeoutException:
            logger.warning("Upstream timeout: %s %s", request.method, url)
            return Response(status_code=504, content=b"upstream timeout")
        except Exception:
            logger.exception("Upstream forward failed: %s %s", request.method, url)
            return Response(status_code=502, content=b"upstream error")

        response_headers = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in _DROP_RESPONSE_HEADERS
        }

        async def _body_iter() -> AsyncIterator[bytes]:
            yield upstream.content

        logger.info(
            "tunnel %s %s -> %d (%d bytes)",
            request.method, url, upstream.status_code, len(upstream.content),
        )

        return StreamingResponse(
            _body_iter(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return app


app = create_app()
