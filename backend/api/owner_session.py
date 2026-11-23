from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.config import settings

router = APIRouter(prefix="/api/owner", tags=["owner"])
COOKIE = "homehub_owner"
TTL = 8 * 60 * 60
_sessions: dict[str, float] = {}
_attempts: deque[float] = deque()
# Serialize secure household-state sends against logout. A send that started
# before logout may finish, but no WSS state frame starts after logout returns.
# The deployment uses one worker and one ASGI event loop for both listeners.
_wss_read_lock = asyncio.Lock()


def valid_context(conn) -> bool:
    """Require a configured exact browser origin, matching Host and direct transport."""
    if not hasattr(conn, "headers") or not hasattr(conn, "scope"):
        return False
    origin = conn.headers.get("origin", "")
    allowed = [x.strip() for x in (settings.HOME_HUB_OWNER_ALLOWED_ORIGINS or "").split(",") if x.strip()]
    if not origin or origin not in allowed or any(h in conn.headers for h in ("forwarded", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-for", "x-real-ip")):
        return False
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or parsed.netloc != conn.headers.get("host", "")):
            return False
        scheme = conn.scope.get("scheme")
        if parsed.scheme == "https":
            return scheme in ("https", "wss")
        if scheme not in ("http", "ws") or not conn.client:
            return False
        # Local transport is an exemption from TLS, never from authentication.
        return parsed.hostname in ("localhost", "127.0.0.1", "::1") and ipaddress.ip_address(conn.client.host).is_loopback
    except (ValueError, AttributeError):
        return False


def valid_session(conn) -> bool:
    if not valid_context(conn):
        return False
    token = conn.cookies.get(COOKIE, "")
    expiry = _sessions.get(token, 0)
    if expiry <= time.monotonic():
        _sessions.pop(token, None)
        return False
    return True


async def send_state_if_authorized(conn, payload: str) -> bool:
    """Send WSS household state only while its session cannot be revoked.

    Existing plain WS clients keep their historical read path. Logout acquires
    the same lock before removing an owner session, so completion of logout is
    a send/revocation ordering barrier, not an attempt to recall in-flight
    transport frames.
    """
    if getattr(conn, "scope", {}).get("scheme") != "wss":
        await conn.send_text(payload)
        return True
    async with _wss_read_lock:
        if not valid_session(conn):
            return False
        await conn.send_text(payload)
        return True


def _verify(password: str, encoded: str) -> bool:
    # Format: pbkdf2_sha256$iterations$base64-salt$base64-digest.
    try:
        algorithm, rounds, salt64, digest64 = encoded.split("$")
        iterations = int(rounds)
        salt = base64.b64decode(salt64, validate=True)
        digest = base64.b64decode(digest64, validate=True)
        if algorithm != "pbkdf2_sha256" or not 600_000 <= iterations <= 2_000_000 or len(salt) < 16 or len(salt) > 64 or len(digest) != 32:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError, OverflowError):
        return False


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/session")
async def login(body: Login, request: Request, response: Response):
    if not valid_context(request):
        raise HTTPException(403, "Owner login requires an allowed origin and HTTPS or direct loopback")
    now = time.monotonic()
    while _attempts and _attempts[0] <= now - 60:
        _attempts.popleft()
    if len(_attempts) >= 5:
        raise HTTPException(429, "Too many login attempts; try again later")
    _attempts.append(now)
    verifier = settings.HOME_HUB_OWNER_PASSWORD_VERIFIER or ""
    if not await asyncio.to_thread(_verify, body.password, verifier):
        raise HTTPException(401, "Invalid credentials or owner login unavailable")
    for token, expiry in list(_sessions.items()):
        if expiry <= now:
            _sessions.pop(token, None)
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.monotonic() + TTL
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
    return {"authenticated": True}


@router.get("/session")
async def status(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    # Status is informational only; command authorization always checks Origin.
    return {"authenticated": _sessions.get(request.cookies.get(COOKIE, ""), 0) > time.monotonic()}


@router.delete("/session")
async def logout(request: Request, response: Response):
    if not valid_context(request):
        raise HTTPException(403, "Invalid origin or transport")
    async with _wss_read_lock:
        _sessions.pop(request.cookies.get(COOKIE, ""), None)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}
