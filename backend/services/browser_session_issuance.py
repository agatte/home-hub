"""Inactive trusted-issuer contract; no HTTP route, token mint or OS proof.

An injected privileged issuer must independently authenticate the operator's
explicit action AND the particular browser/kiosk recipient, TLS delivery channel
and CSRF proof. Python objects, headers, same UID and synthetic signatures do
not establish that authority. Evidence is opaque to this source-only validator;
no configured, genuinely protected issuer/evidence means NO issuance.
"""
from dataclasses import dataclass, field
import asyncio
import inspect
import secrets
import time
from typing import Protocol
from urllib.parse import urlsplit

from backend.services.identity_broker_verify_client import (
    TOKEN, VERSION, decode_frame, valid_hex, valid_time,
)
from backend.services.ws_authenticated_boundary import Endpoint

MAX_AGE = 3600
COOKIE = "__Host-homehub_ws"


@dataclass(frozen=True, repr=False)
class IssuanceRequest:
    nonce: str
    profile: str
    origin: str
    recipient_id: str
    generation: str
    action: str


class PrivilegedBrowserIssuer(Protocol):
    async def issue_browser_session(self, request: IssuanceRequest, *,
                                    operator_action: object, recipient_evidence: object,
                                    csrf_evidence: object) -> bytes:
        """Separate privileged path, NEVER the verify socket or backend DB.

        Authenticate evidence afresh, bind action/profile/recipient/origin/nonce/
        generation, check exact Origin+Host+TLS and session-bound CSRF. Own random
        session token, one-way verifier, expiry/revocation, durable registry and
        independent journal/floor. A raw native bearer must NEVER be returned.
        Rotate revokes old session before acknowledging new delivery (no overlap).
        Uncertain/cancelled delivery requires privileged revocation, not retry.
        Restore invalidates all sessions by generation before serving again.
        Return framed JSON only via protected channel; never log secret/errors.
        """
        ...


@dataclass(frozen=True, repr=False)
class CookieDelivery:
    """Only a Set-Cookie header sink may consume this; no JSON/JS/token accessor.

    Issuer owns cleanup of uncertain delivery, logout/revoke and rotation. A
    successful logout requires fresh durable broker revocation BEFORE cookie
    clearing; clearing alone never revokes. No public logout route exists here.
    """
    _header: bytes = field(repr=False)

    def set_cookie_header(self) -> tuple[bytes, bytes]:
        return b"set-cookie", self._header


def delivery_matches(scope, endpoint):
    """Necessary HTTP delivery facts, never sufficient recipient/OS authority.

    A future route must extract from trusted ASGI TLS termination without
    forwarded trust, require same-origin POST plus independently verified CSRF,
    return empty no-store response and send Set-Cookie only to proven recipient.
    """
    try:
        if (type(scope) is not dict or scope.get("type") != "http"
                or scope.get("scheme") != "https" or scope.get("method") != "POST"
                or scope.get("query_string", b"") != b""):
            return False
        raw = scope.get("headers", [])
        if len(raw) > 32 or sum(len(k) + len(v) for k, v in raw) > 8192:
            return False
        headers = {}
        for key, value in raw:
            key, value = key.decode("ascii").lower(), value.decode("ascii")
            if key in headers or key == "forwarded" or key.startswith("x-forwarded-"):
                return False
            headers[key] = value
        return (headers.get("host") == urlsplit(endpoint.origin).netloc
                and headers.get("origin") == endpoint.origin)
    except Exception:
        return False


async def issue_cookie(issuer: PrivilegedBrowserIssuer | None, *, endpoint: Endpoint,
                       recipient_id: str, generation, scope: dict,
                       operator_action=None, recipient_evidence=None, csrf_evidence=None,
                       action="issue", clock=time.time) -> CookieDelivery | None:
    """Pure trusted-injection orchestration; deliberately has no public adapter.

    Endpoint/profile/recipient/generation must be server-owned configuration.
    Evidence is not a boolean approval; only the privileged issuer can validate
    it. No timeout/retry here: the integrating privileged delivery owner MUST
    bound admission/work/deadlines and reconcile uncertain delivery on cancel.
    """
    if (type(endpoint) is not Endpoint or endpoint.profile not in {"owner_browser", "kiosk"}
            or not endpoint.origin.startswith("https://") or not valid_hex(recipient_id)
            or type(action) is not str or action not in {"issue", "rotate"}
            or not delivery_matches(scope, endpoint) or not callable(generation)
            or any(value is None or type(value) is bool for value in
                   (operator_action, recipient_evidence, csrf_evidence))
            or not inspect.iscoroutinefunction(getattr(issuer, "issue_browser_session", None))):
        return None
    try:
        epoch = generation()
        if not valid_hex(epoch):
            return None
        request = IssuanceRequest(secrets.token_hex(16), endpoint.profile, endpoint.origin,
                                  recipient_id, epoch, action)
        frame = await issuer.issue_browser_session(
            request, operator_action=operator_action, recipient_evidence=recipient_evidence,
            csrf_evidence=csrf_evidence)
        response = decode_frame(frame)
        if response.keys() != {"version", "nonce", "status", "profile", "origin",
                               "recipient_id", "generation", "kind", "token", "expires_at"}:
            return None
        if (type(response["version"]) is not int or response["version"] != VERSION
                or response["nonce"] != request.nonce or response["status"] != "issued"
                or response["profile"] != endpoint.profile or response["origin"] != endpoint.origin
                or response["recipient_id"] != recipient_id or response["generation"] != epoch
                or generation() != epoch or response["kind"] != "browser_session"
                or type(response["token"]) is not str or not TOKEN.fullmatch(response["token"])):
            return None
        now, expiry = clock(), response["expires_at"]
        if not valid_time(now) or not valid_time(expiry) or not 1 <= expiry - now <= MAX_AGE:
            return None
        age = int(expiry - now)  # conservative rounding; reverify every WS use
        return CookieDelivery((f"{COOKIE}={response['token']}; Secure; HttpOnly; "
                               f"SameSite=Strict; Path=/; Max-Age={age}").encode("ascii"))
    except asyncio.CancelledError:
        raise
    except Exception:
        return None  # never expose raw issuer exception, token or validation input
