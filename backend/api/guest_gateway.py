"""Public guest gateway for the isolated Google Guest Wi-Fi path.

The gateway is intentionally separate from the main FastAPI app. Cloudflare
may expose this process, but it forwards only the visitor UI and explicit
/api/guest capability surface. It never forwards generic HomeHub routes.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections import deque
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend.config import settings

logger = logging.getLogger("home_hub.guest_gateway")

UPSTREAM = "http://127.0.0.1:8000"
COOKIE_NAME = "homehub_guest_session"
MAX_BODY_BYTES = 8 * 1024
API_RATE_LIMIT = 60
API_RATE_WINDOW_SECONDS = 60.0

_ALLOWED_API: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/api/guest/wifi$")),
    ("GET", re.compile(r"^/api/guest/state$")),
    ("GET", re.compile(r"^/api/guest/art$")),
    ("GET", re.compile(r"^/api/guest/scenes$")),
    ("GET", re.compile(r"^/api/guest/vibes$")),
    ("GET", re.compile(r"^/api/guest/bar$")),
    ("GET", re.compile(r"^/api/guest/plants$")),
    ("POST", re.compile(r"^/api/guest/scene/[a-z_-]+$")),
    ("POST", re.compile(r"^/api/guest/scene/[a-z_-]+/reset$")),
    ("POST", re.compile(r"^/api/guest/vibe/[a-z_-]+$")),
    ("POST", re.compile(r"^/api/guest/handback$")),
    ("POST", re.compile(r"^/api/guest/effect/[a-z_-]+$")),
    ("POST", re.compile(r"^/api/guest/brightness/step/-?\d+$")),
    ("POST", re.compile(r"^/api/guest/kitchen$")),
    ("POST", re.compile(r"^/api/guest/sonos/(play|pause|next)$")),
    ("POST", re.compile(r"^/api/guest/sonos/volume/(up|down)$")),
    ("POST", re.compile(r"^/api/guest/toast$")),
)

_DROP_REQUEST_HEADERS = frozenset({
    "connection", "cookie", "host", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
    "content-length", "x-api-key", "x-skill-token", "x-tunnel-origin",
    # The public gateway terminates client identity.  Never relay proxy/client-IP
    # headers into the loopback HomeHub hop: uvicorn trusts X-Forwarded-For from
    # loopback and would otherwise reclassify a session-authenticated guest as
    # the public internet client, causing the main write gate to reject it.
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-port",
    "x-forwarded-proto", "x-real-ip", "cf-connecting-ip", "cf-visitor",
})

_DROP_RESPONSE_HEADERS = frozenset({
    "connection", "keep-alive", "transfer-encoding", "upgrade",
    "content-encoding", "content-length", "set-cookie",
})


def _is_allowed_api(method: str, path: str) -> bool:
    return any(m == method and pattern.match(path) for m, pattern in _ALLOWED_API)


def _safe_forward_path(prefix: str, suffix: str) -> str:
    """Join a captured route suffix without letting a proxy path escape its prefix."""
    # Starlette decodes one layer before path converters run. Reject any
    # remaining percent-encoding as well so double-encoded dot segments cannot
    # be decoded/normalized by httpx or the upstream ASGI server. Guest routes
    # and Svelte build assets never require percent escapes in path segments.
    if "%" in suffix or "\\" in suffix or "\x00" in suffix:
        raise HTTPException(status_code=404, detail="Not found")
    segments = [segment for segment in suffix.split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise HTTPException(status_code=404, detail="Not found")
    base = prefix.rstrip("/")
    return f"{base}/{'/'.join(segments)}" if segments else base


def _is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


class _AccessState:
    def __init__(self) -> None:
        self.invites: dict[str, float] = {}
        self.sessions: dict[str, float] = {}
        self.buckets: dict[str, deque[float]] = {}
        self.lock = asyncio.Lock()

    def cleanup_locked(self, now: float) -> None:
        self.invites = {k: v for k, v in self.invites.items() if v > now}
        expired = {k for k, v in self.sessions.items() if v <= now}
        for key in expired:
            self.sessions.pop(key, None)
            self.buckets.pop(key, None)


async def _require_session(request: Request) -> str:
    session_id = request.cookies.get(COOKIE_NAME, "")
    state: _AccessState = request.app.state.access
    now = time.time()
    async with state.lock:
        state.cleanup_locked(now)
        expires = state.sessions.get(session_id)
        if not session_id or not expires or expires <= now:
            raise HTTPException(status_code=401, detail="Guest session required")
    return session_id


async def _check_rate_limit(request: Request, session_id: str) -> None:
    state: _AccessState = request.app.state.access
    now = time.monotonic()
    cutoff = now - API_RATE_WINDOW_SECONDS
    async with state.lock:
        bucket = state.buckets.setdefault(session_id, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= API_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too many guest requests")
        bucket.append(now)


def create_app(
    *,
    upstream: str = UPSTREAM,
    public_url: Optional[str] = None,
    invite_ttl: Optional[int] = None,
    session_ttl: Optional[int] = None,
    client_transport: Optional[httpx.AsyncBaseTransport] = None,
) -> FastAPI:
    """Build the guest-only public gateway app."""
    public = (public_url if public_url is not None else settings.GUEST_PUBLIC_URL).rstrip("/")
    invite_seconds = invite_ttl or settings.GUEST_INVITE_TTL_SECONDS
    session_seconds = session_ttl or settings.GUEST_SESSION_TTL_SECONDS

    app = FastAPI(title="HomeHub Guest Gateway", docs_url=None, redoc_url=None)
    app.state.access = _AccessState()

    @app.on_event("startup")
    async def _startup() -> None:
        app.state.client = httpx.AsyncClient(
            base_url=upstream,
            timeout=6.0,
            transport=client_transport,
        )
        logger.info("Guest gateway started for %s", public or "<unconfigured>")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await app.state.client.aclose()

    @app.post("/internal/invite")
    async def create_invite(request: Request) -> dict:
        if not _is_local_request(request):
            raise HTTPException(status_code=404, detail="Not found")
        if not public:
            raise HTTPException(status_code=503, detail="Guest public URL not configured")
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + invite_seconds
        state: _AccessState = request.app.state.access
        async with state.lock:
            state.cleanup_locked(time.time())
            state.invites[token] = expires_at
        return {
            "status": "ok",
            "join_url": f"{public}/join/{token}",
            "expires_in": invite_seconds,
        }

    @app.post("/internal/revoke")
    async def revoke_sessions(request: Request) -> dict:
        if not _is_local_request(request):
            raise HTTPException(status_code=404, detail="Not found")
        state: _AccessState = request.app.state.access
        async with state.lock:
            state.invites.clear()
            state.sessions.clear()
            state.buckets.clear()
        return {"status": "ok"}

    @app.get("/internal/status")
    async def internal_status(request: Request) -> dict:
        if not _is_local_request(request):
            raise HTTPException(status_code=404, detail="Not found")
        state: _AccessState = request.app.state.access
        async with state.lock:
            state.cleanup_locked(time.time())
            return {
                "status": "ok",
                "configured": bool(public),
                "public_url": public or None,
                "active_invites": len(state.invites),
                "active_sessions": len(state.sessions),
            }

    @app.get("/join/{token}")
    async def join(token: str, request: Request) -> Response:
        state: _AccessState = request.app.state.access
        now = time.time()
        async with state.lock:
            state.cleanup_locked(now)
            expires = state.invites.pop(token, None)
            if not expires or expires <= now:
                raise HTTPException(status_code=404, detail="Invite expired or invalid")
            session_id = secrets.token_urlsafe(32)
            state.sessions[session_id] = now + session_seconds

        response = RedirectResponse(url="/guest", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=session_seconds,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response

    async def _forward(request: Request, path: str) -> Response:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Guest request too large")
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _DROP_REQUEST_HEADERS
        }
        headers["X-Source"] = "guest_gateway"
        url = path
        if request.url.query:
            url = f"{url}?{request.url.query}"
        try:
            upstream_response = await request.app.state.client.request(
                request.method,
                url,
                headers=headers,
                content=body,
            )
        except httpx.TimeoutException:
            return Response(status_code=504, content=b"guest upstream timeout")
        except httpx.HTTPError:
            logger.exception("Guest upstream failed: %s %s", request.method, url)
            return Response(status_code=502, content=b"guest upstream unavailable")

        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in _DROP_RESPONSE_HEADERS
        }
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )

    @app.api_route("/_app/{path:path}", methods=["GET"])
    async def frontend_assets(path: str, request: Request) -> Response:
        return await _forward(request, _safe_forward_path("/_app", path))

    @app.get("/favicon.svg")
    async def favicon(request: Request) -> Response:
        return await _forward(request, "/favicon.svg")

    @app.api_route("/guest{path:path}", methods=["GET"])
    async def guest_frontend(path: str, request: Request) -> Response:
        await _require_session(request)
        return await _forward(request, _safe_forward_path("/guest", path))

    @app.api_route("/api/guest/{path:path}", methods=["GET", "POST"])
    async def guest_api(path: str, request: Request) -> Response:
        full_path = f"/api/guest/{path}"
        if not _is_allowed_api(request.method, full_path):
            raise HTTPException(status_code=404, detail="Not found")
        session_id = await _require_session(request)
        await _check_rate_limit(request, session_id)
        return await _forward(request, full_path)

    return app


app = create_app()
