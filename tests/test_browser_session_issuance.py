"""Synthetic issuer capabilities exercise validation, NOT actual OS authority."""
import asyncio

import pytest

from backend.services.browser_session_issuance import (
    MAX_AGE, CookieDelivery, issue_cookie,
)
from backend.services.identity_broker_verify_client import encode_frame
from backend.services.ws_authenticated_boundary import Endpoint
from tests.test_identity_broker_verify_client import GENERATION, TOKEN

RECIPIENT = "4" * 32


class FakePrivilegedIssuer:
    def __init__(self):
        self.operator, self.recipient, self.csrf = object(), object(), object()
        self.calls = 0
        self.mutate = lambda r: r
        self.generation = GENERATION
        self.expiry = 1100
        self.revoked_old = False
        self.deny = False

    async def issue_browser_session(self, request, *, operator_action,
                                    recipient_evidence, csrf_evidence):
        self.calls += 1
        # These object identities are ONLY a fixture gate, not OS/recipient proof.
        if (operator_action is not self.operator or recipient_evidence is not self.recipient
                or csrf_evidence is not self.csrf or self.deny):
            raise PermissionError("synthetic issuer denied")
        if request.action == "rotate":
            self.revoked_old = True
        return encode_frame(self.mutate({
            "version": 1, "nonce": request.nonce, "status": "issued", "profile": request.profile,
            "origin": request.origin, "recipient_id": request.recipient_id,
            "generation": self.generation, "kind": "browser_session", "token": TOKEN,
            "expires_at": self.expiry}))


def args(issuer, profile="owner_browser"):
    return dict(endpoint=Endpoint("https://hub.test", profile), recipient_id=RECIPIENT,
                generation=lambda: issuer.generation, scope={
                    "type": "http", "scheme": "https", "method": "POST", "query_string": b"",
                    "headers": [(b"host", b"hub.test"), (b"origin", b"https://hub.test")]},
                operator_action=issuer.operator, recipient_evidence=issuer.recipient,
                csrf_evidence=issuer.csrf, clock=lambda: 1000)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["owner_browser", "kiosk"])
async def test_cookie_only_secure_http_delivery(profile):
    issuer = FakePrivilegedIssuer()
    delivery = await issue_cookie(issuer, **args(issuer, profile))
    assert type(delivery) is CookieDelivery
    key, value = delivery.set_cookie_header()
    assert key == b"set-cookie"
    assert value == ("__Host-homehub_ws=" + TOKEN +
                     "; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=100").encode()
    assert b"Domain" not in value
    assert TOKEN not in repr(delivery)
    assert not hasattr(delivery, "token")
    assert not hasattr(delivery, "json")


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("operator_action", None), ("recipient_evidence", None), ("csrf_evidence", None),
    ("operator_action", True), ("recipient_evidence", True), ("csrf_evidence", True),
    ("operator_action", object()), ("recipient_evidence", object()), ("csrf_evidence", object()),
    ("recipient_id", "header-asserted"), ("action", "enroll"), ("action", "revoke"),
    ("endpoint", Endpoint("https://hub.test", "windows_desktop")),
    ("endpoint", Endpoint("http://127.0.0.1", "kiosk")),
])
async def test_no_issuance_without_both_trusted_authorities_and_csrf(field, value):
    issuer = FakePrivilegedIssuer()
    options = args(issuer)
    options[field] = value
    assert await issue_cookie(issuer, **options) is None


@pytest.mark.asyncio
async def test_absent_issuer_is_closed():
    issuer = FakePrivilegedIssuer()
    assert await issue_cookie(None, **args(issuer)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["origin", "host", "forwarded", "x-forwarded-proto",
    "duplicate", "tls", "get", "query", "missing-origin", "invalid-header"])
async def test_cross_origin_host_tls_and_csrf_delivery_gates(mutation):
    issuer = FakePrivilegedIssuer()
    options = args(issuer)
    scope = options["scope"]
    headers = scope["headers"]
    if mutation == "origin":
        headers[1] = (b"origin", b"https://evil.test")
    elif mutation == "host":
        headers[0] = (b"host", b"evil.test")
    elif mutation in {"forwarded", "x-forwarded-proto"}:
        headers.append((mutation.encode(), b"https"))
    elif mutation == "duplicate":
        headers.append(headers[0])
    elif mutation == "tls":
        scope["scheme"] = "http"
    elif mutation == "get":
        scope["method"] = "GET"
    elif mutation == "query":
        scope["query_string"] = b"token=synthetic"
    elif mutation == "missing-origin":
        headers.pop()
    else:
        headers.append((b"x-test", b"\xff"))
    assert await issue_cookie(issuer, **options) is None
    assert issuer.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("version", True), ("nonce", "0" * 32), ("status", "verified"),
    ("profile", "kiosk"), ("origin", "https://evil.test"),
    ("recipient_id", "5" * 32), ("generation", "6" * 32), ("kind", "native_bearer"),
    ("token", TOKEN + "\r\nInjected: yes"), ("token", "native"),
    ("expires_at", 1000), ("expires_at", 1000.9), ("expires_at", 1001 + MAX_AGE),
    ("expires_at", True), ("expires_at", "1100"), ("extra", TOKEN),
])
async def test_issuer_exact_result_bound_to_recipient_and_request(field, value):
    issuer = FakePrivilegedIssuer()
    issuer.mutate = lambda r: dict(r, **{field: value})
    assert await issue_cookie(issuer, **args(issuer)) is None


@pytest.mark.asyncio
async def test_rotation_restore_and_revocation_before_delivery():
    issuer = FakePrivilegedIssuer()
    assert await issue_cookie(issuer, **dict(args(issuer), action="rotate"))
    assert issuer.revoked_old
    original = issuer.issue_browser_session
    async def restored(request, **kwargs):
        result = await original(request, **kwargs)
        issuer.generation = "7" * 32
        return result
    issuer.issue_browser_session = restored
    assert await issue_cookie(issuer, **args(issuer)) is None
    issuer.deny = True
    assert await issue_cookie(issuer, **args(issuer)) is None


@pytest.mark.asyncio
async def test_sensitive_error_suppression_and_cancel_no_delivery():
    issuer = FakePrivilegedIssuer()
    async def failed(*args, **kwargs):
        raise RuntimeError(TOKEN)
    issuer.issue_browser_session = failed
    assert await issue_cookie(issuer, **args(issuer)) is None
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()
    issuer.issue_browser_session = cancelled
    with pytest.raises(asyncio.CancelledError):
        await issue_cookie(issuer, **args(issuer))


@pytest.mark.asyncio
async def test_issued_cookie_through_actual_asgi_route_and_protected_verifier():
    from tests.test_identity_broker_verify_client import FakeProtectedBroker, client
    from tests.test_websocket import exchange, frames, state_app
    from tests.support.ws_runtime import scope

    issuer = FakePrivilegedIssuer()
    delivery = await issue_cookie(issuer, **args(issuer))
    broker = FakeProtectedBroker()
    verifier = client(broker)
    app = state_app(authorize=verifier.authorize)
    request = scope()
    # Browser sends only cookie name=value, attributes stay in delivery header.
    request["headers"][-1] = (b"cookie", delivery.set_cookie_header()[1].split(b";", 1)[0])
    result = await exchange(app, request_scope=request)
    assert result[0]["type"] == "websocket.accept"
    assert frames(result)
    assert TOKEN not in str(result)
    broker.status = "revoked"
    result = await exchange(app, request_scope=request)
    assert result == [{"type": "websocket.close", "code": 1008, "reason": ""}]


@pytest.mark.asyncio
async def test_issuer_replay_and_malformed_frame_fail_closed(caplog, capsys):
    issuer = FakePrivilegedIssuer()
    original = issuer.issue_browser_session
    saved = []
    async def replay(request, **kwargs):
        if not saved:
            saved.append(await original(request, **kwargs))
        return saved[0]
    issuer.issue_browser_session = replay
    assert await issue_cookie(issuer, **args(issuer))
    assert await issue_cookie(issuer, **args(issuer)) is None
    async def malformed(*a, **kw):
        return b'\x00\x00\x00\x02{'  # truncated response
    issuer.issue_browser_session = malformed
    assert await issue_cookie(issuer, **args(issuer)) is None
    async def secret_error(*a, **kw):
        raise RuntimeError(TOKEN)
    issuer.issue_browser_session = secret_error
    assert await issue_cookie(issuer, **args(issuer)) is None
    captured = capsys.readouterr()
    assert TOKEN not in caplog.text + captured.out + captured.err
