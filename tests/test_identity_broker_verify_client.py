"""Synthetic protected transport ONLY; no socket, host or credential authority."""
import asyncio
import json
import struct

import pytest

from backend.identity_core import Identity
from backend.identity_policy import PROFILES, WS, WS_LIGHT_COMMAND
from backend.services.identity_broker_verify_client import (
    MAX_FRAME, ProtocolDenied, VerifyClient, decode_frame, encode_frame, read_frame,
)
from backend.services.websocket_manager import WebSocketManager, WebSocketRuntimeConfiguration
from backend.services.ws_authenticated_boundary import Endpoint
from tests.test_ws_authenticated_boundary import Socket

TOKEN = "0" * 32 + "." + "A" * 43  # deliberate noncredential
GENERATION = "1" * 32
PRINCIPAL = "2" * 32


class FakeProtectedBroker:
    """Models final serialized decision, never claims Linux or OS attestation."""
    def __init__(self, profile="owner_browser"):
        self.profile = profile
        self.generation = GENERATION
        self.token_generation = GENERATION
        self.token = TOKEN
        self.revision = 1
        self.status = "verified"
        self.expiry = 1100
        self.mutate = lambda r: r
        self.calls = 0
        self.gate = None

    async def exchange_verify(self, frame):
        self.calls += 1
        request = decode_frame(frame)
        assert request.keys() == {"version", "method", "nonce", "token", "operation", "lane", "generation", "revision"}
        assert request["version"] == 1 and request["method"] == "verify"
        if self.gate is not None:
            await self.gate.wait()
        status = self.status
        if (request["token"] != self.token or self.token_generation != self.generation
                or request["generation"] != self.generation
                or request["revision"] != self.revision):
            status = "denied"
        response = {"version": 1, "nonce": request["nonce"], "status": status,
                    "generation": self.generation, "revision": self.revision}
        if status == "verified":
            response.update(principal_id=PRINCIPAL, profile=self.profile,
                            source=PROFILES[self.profile].source, lane=request["lane"],
                            operation=request["operation"], expires_at=self.expiry,
                            kind="browser_session" if self.profile in {"owner_browser", "kiosk"}
                            else "native_bearer")
        result = self.mutate(response)
        return result if type(result) is bytes else encode_frame(result)


def client(broker, **kwargs):
    return VerifyClient(broker, generation=lambda: broker.generation,
                        revision=lambda: broker.revision, clock=lambda: 1000, **kwargs)


async def verify(verifier, **kwargs):
    return await verifier.authorize(TOKEN, WS, lane="browser", stage="admission", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,lane", [("owner_browser", "browser"), ("kiosk", "display"),
                                         ("windows_desktop", "display"), ("desktop_notifier", "notifier")])
async def test_exact_identity_and_no_cache(profile, lane):
    broker = FakeProtectedBroker(profile)
    verifier = client(broker)
    identity = await verifier.authorize(TOKEN, WS, lane=lane, stage="admission")
    assert type(identity) is Identity
    assert identity == Identity(PRINCIPAL, profile, PROFILES[profile].source, lane)
    broker.status = "revoked"
    assert await verifier.authorize(TOKEN, WS, lane=lane, stage="active") is None
    assert broker.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["denied", "revoked", "quarantined", "unavailable", "error", "expired", "unknown", True])
async def test_all_nonverified_statuses_deny(status):
    broker = FakeProtectedBroker()
    broker.status = status
    assert await verify(client(broker)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 2), ("nonce", "x"), ("nonce", "0" * 32),
    ("generation", "0" * 32), ("principal_id", ""), ("principal_id", TOKEN),
    ("revision", True), ("revision", 0),
    ("profile", "forged"), ("profile", []), ("source", "desktop"),
    ("lane", "display"), ("operation", WS_LIGHT_COMMAND), ("kind", "native_bearer"),
    ("expires_at", True), ("expires_at", 1000), ("expires_at", 999),
    ("expires_at", "1100"), ("extra", TOKEN), ("token", TOKEN),
])
async def test_malformed_or_forged_response_denies(field, value):
    broker = FakeProtectedBroker()
    broker.mutate = lambda r: dict(r, **{field: value})
    assert await verify(client(broker)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    (TOKEN, "admin", "browser", "admission"), (TOKEN, WS, "unknown", "active"),
    (TOKEN, WS, "browser", "unknown"), (TOKEN, WS, "browser", []),
    ("bad", WS, "browser", "admission"),
])
async def test_invalid_request_never_calls_io(args):
    broker = FakeProtectedBroker()
    assert await client(broker).authorize(args[0], args[1], lane=args[2], stage=args[3]) is None
    assert broker.calls == 0


@pytest.mark.asyncio
async def test_claimed_source_denied_and_no_admin_method():
    broker = FakeProtectedBroker()
    verifier = client(broker)
    assert await verify(verifier, claimed_source="owner") is None
    assert broker.calls == 0
    assert not hasattr(verifier, "admin")
    assert TOKEN not in repr(verifier)


def raw(body):
    return struct.pack("!I", len(body)) + body


@pytest.mark.parametrize("frame", [b"", b"\x00", struct.pack("!I", 0),
    struct.pack("!I", MAX_FRAME + 1), raw(b'{"nonce":1,"nonce":2}'),
    raw(b'[]'), raw(b'{"x":NaN}'), raw(b'{"x":Infinity}'), raw(b'\xff'),
    raw(b'{'), raw(b'{}') + b'x', raw(b'{}')[:-1], raw(b'{}') + raw(b'{}'),
    raw(b'"' + b'A' * MAX_FRAME + b'"')])
def test_strict_frames_and_sanitized_exception(frame):
    with pytest.raises(ProtocolDenied) as error:
        decode_frame(frame)
    assert str(error.value) == "Broker contract denied"
    assert error.value.__context__ is None
    assert error.value.__cause__ is None


@pytest.mark.asyncio
async def test_partial_stream_helper_bounds_before_body_allocation():
    reader = asyncio.StreamReader()
    frame = encode_frame({"ok": True})
    task = asyncio.create_task(read_frame(reader.readexactly))
    for byte in frame:
        reader.feed_data(bytes([byte]))
        await asyncio.sleep(0)
    assert await task == frame
    for broken in [frame[:-1], frame[:2], struct.pack("!I", MAX_FRAME + 1)]:
        reader = asyncio.StreamReader()
        reader.feed_data(broken)
        reader.feed_eof()
        with pytest.raises(ProtocolDenied):
            await read_frame(reader.readexactly)


@pytest.mark.asyncio
async def test_timeout_cancellation_capacity_and_late_revocation():
    broker = FakeProtectedBroker()
    broker.gate = asyncio.Event()
    verifier = client(broker, timeout=0.01, active_capacity=1)
    assert await verify(verifier) is None  # underlying work stays counted
    assert len(verifier._pending["admission"]) == 1
    assert await verify(verifier) is None
    active = asyncio.create_task(verifier.authorize(TOKEN, WS, lane="browser", stage="active"))
    await asyncio.sleep(0)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert len(verifier._pending["active"]) == 1
    assert await verifier.authorize(TOKEN, WS, lane="browser", stage="active") is None
    assert broker.calls == 2  # active capacity reserved independently
    broker.status = "revoked"  # revoke wins before modeled final decision
    broker.gate.set()
    await asyncio.gather(*verifier._pending["admission"], *verifier._pending["active"])
    await asyncio.sleep(0)
    assert not any(verifier._pending.values())
    assert await verify(verifier) is None


@pytest.mark.asyncio
async def test_generation_changes_while_request_in_flight():
    broker = FakeProtectedBroker()
    gate = asyncio.Event()
    original = broker.exchange_verify
    async def delayed(frame):
        result = await original(frame)
        await gate.wait()
        return result
    broker.exchange_verify = delayed
    verifier = client(broker)
    task = asyncio.create_task(verify(verifier))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    broker.generation = "3" * 32
    gate.set()
    assert await task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["revoke", "rotate", "expiry"])
async def test_delayed_pre_mutation_response_never_grants(mutation):
    broker = FakeProtectedBroker()
    verifier = client(broker)
    now = [1000]
    verifier._clock = lambda: now[0]
    original = broker.exchange_verify
    async def delayed(frame):
        result = await original(frame)
        if mutation == "expiry":
            now[0] = 1100
        else:
            broker.revision += 1  # trusted state observer sees committed mutation
            broker.status = "revoked"
        return result
    broker.exchange_verify = delayed
    assert await verify(verifier) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["duplicate", "oversize", "truncated", "surplus", "missing", "unavailable"])
async def test_transport_failures_through_authorizer_are_closed(damage):
    broker = FakeProtectedBroker()
    async def broken(frame):
        if damage == "unavailable":
            raise OSError(TOKEN)
        if damage == "duplicate":
            return raw(b'{"status":"verified","status":"denied"}')
        if damage == "oversize":
            return struct.pack("!I", MAX_FRAME + 1)
        if damage == "truncated":
            return encode_frame({"status": "verified"})[:-1]
        if damage == "surplus":
            return encode_frame({}) + encode_frame({})
        return encode_frame({})
    broker.exchange_verify = broken
    assert await verify(client(broker)) is None


@pytest.mark.asyncio
async def test_replayed_response_and_sensitive_adapter_error_deny(caplog, capsys):
    broker = FakeProtectedBroker()
    verifier = client(broker)
    saved = []
    def capture(response):
        saved.append(response)
        return response
    broker.mutate = capture
    assert await verify(verifier)
    broker.mutate = lambda _: saved[0]
    assert await verify(verifier) is None
    async def broken(_):
        raise RuntimeError(TOKEN)
    broker.exchange_verify = broken
    assert await verify(verifier) is None
    captured = capsys.readouterr()
    assert TOKEN not in caplog.text + captured.out + captured.err


@pytest.mark.asyncio
async def test_rotation_and_restore_do_not_revive_old_session():
    broker = FakeProtectedBroker()
    verifier = client(broker)
    assert await verify(verifier)
    replacement = "9" * 32 + "." + "B" * 43
    broker.token = replacement
    broker.revision += 1
    assert await verify(verifier) is None
    assert await verifier.authorize(replacement, WS, lane="browser", stage="active")
    broker.generation = "8" * 32
    assert await verifier.authorize(replacement, WS, lane="browser", stage="active") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["owner_browser", "kiosk", "windows_desktop", "desktop_notifier"])
async def test_real_manager_projection_and_fresh_session_revocation(profile):
    broker = FakeProtectedBroker(profile)
    verifier = client(broker)
    endpoint = Endpoint("https://hub.test", profile)
    manager = WebSocketManager(configuration=WebSocketRuntimeConfiguration(
        verifier.authorizer(), (endpoint,), True))
    headers = [("host", "hub.test")]
    if profile in {"owner_browser", "kiosk"}:
        headers += [("origin", endpoint.origin), ("cookie", "__Host-homehub_ws=" + TOKEN)]
    else:
        headers += [("authorization", "Bearer " + TOKEN)]
    socket = Socket(headers)
    assert await manager._boundary.admit(socket)
    await manager.broadcast("mode_update", {"mode": "Home", "time_period": "day", "secret": TOKEN})
    assert TOKEN not in json.dumps(socket.frames)
    if profile == "desktop_notifier":
        assert not socket.frames
    else:
        assert socket.frames[0]["data"]["mode"] == "Home"
    broker.status = "revoked"
    await manager.broadcast("notification" if profile == "desktop_notifier" else "mode_update",
                            {"title": "Synthetic", "mode": "Home"})
    assert manager.connection_count == 0
    socket.close.assert_awaited_with(code=1008)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,wire_profile", [("owner_browser", "windows_desktop"),
    ("kiosk", "owner_browser"), ("windows_desktop", "kiosk"),
    ("desktop_notifier", "windows_desktop")])
async def test_broker_identity_cannot_select_endpoint_profile(profile, wire_profile):
    broker = FakeProtectedBroker(wire_profile)
    manager = WebSocketManager(configuration=WebSocketRuntimeConfiguration(
        client(broker).authorizer(), (Endpoint("https://hub.test", profile),), True))
    browser = profile in {"owner_browser", "kiosk"}
    headers = [("host", "hub.test")]
    headers += ([("origin", "https://hub.test"), ("cookie", "__Host-homehub_ws=" + TOKEN)]
                if browser else [("authorization", "Bearer " + TOKEN)])
    socket = Socket(headers)
    assert not await manager._boundary.admit(socket)
    socket.accept.assert_not_awaited()
