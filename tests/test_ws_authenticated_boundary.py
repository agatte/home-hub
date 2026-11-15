"""Offline boundary proof only: no app import, hardware, network or real secrets.

Browser-ready fixtures model a FUTURE issuer; they do not implement provisioning
or authorize cutover. Native projection files predate this step and are unchanged.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from backend.identity_core import IdentityStore
from backend.identity_policy import WS, WS_LIGHT_COMMAND, WS_SONOS_COMMAND
from backend.services.ws_authenticated_boundary import AuthenticatedBoundary, Endpoint, TrustedAsyncAuthorizer, project_event


class Socket:
    def __init__(self, headers, *, scheme="wss", query=b"", path="/ws"):
        self.scope = {"path": path, "scheme": scheme, "query_string": query,
                      "headers": [(k.encode(), v.encode()) for k, v in headers]}
        self.accept = AsyncMock()
        self.close = AsyncMock()
        self.send_text = AsyncMock()
        self.receive_text = AsyncMock()

    @property
    def frames(self):
        return [json.loads(c.args[0]) for c in self.send_text.call_args_list]


@pytest.fixture
def registry(tmp_path):
    cap, now = object(), [1000.0]
    store = IdentityStore(tmp_path / "synthetic.sqlite", local_capability=cap, clock=lambda: now[0])
    async def authorize(token, operation, *, stage, **kwargs):
        assert stage in {"admission", "active"}
        # Actual SQLite connection and all verification are owned by the worker.
        # Shielded by the boundary retaining the task until work has settled.
        def work():
            worker = IdentityStore(tmp_path / "synthetic.sqlite", local_capability=object(),
                                   clock=lambda: now[0])
            try:
                return worker.authorize(token, operation, **kwargs)
            finally:
                worker.close()
        return await asyncio.to_thread(work)
    store._async_authorize = authorize
    yield store, cap, now
    store.close()


def setup(registry, profile="windows_desktop", **kwargs):
    store, cap, _ = registry
    enrolled = store.enroll(profile, capability=cap, lifetime=60)
    endpoint = Endpoint("https://hub.test:8443", profile)
    boundary = AuthenticatedBoundary(TrustedAsyncAuthorizer(store._async_authorize), [endpoint], **kwargs)
    headers = [("host", "hub.test:8443")]
    if profile in {"owner_browser", "kiosk"}:
        headers += [("origin", endpoint.origin),
                    ("cookie", f"__Host-homehub_ws={enrolled.token}")]
    else:
        headers += [("authorization", f"Bearer {enrolled.token}")]
    return boundary, Socket(headers), enrolled


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("origin,profile", [
    ("https://*.test", "owner_browser"), ("http://hub.test", "owner_browser"),
    ("http://192.168.1.2", "kiosk"), ("http://localhost", "kiosk"),
    ("https://hub.test/", "kiosk"), ("https://user@hub.test", "kiosk"),
    ("https://hub.test?token=x", "kiosk"), ("https://hub.test:bad", "kiosk"),
    ("https://HUB.test", "kiosk"), ("https://hub.test", "unknown"),
    ("https://hub.test:0443", "kiosk"),
])
def test_configuration_rejects_wildcard_ambiguous_or_insecure_origin(origin, profile):
    with pytest.raises(ValueError):
        Endpoint(origin, profile)


@pytest.mark.parametrize("mutation", [
    "anonymous", "host", "cross-origin", "forwarded", "x-forwarded-host",
    "query", "duplicate-host", "subprotocol", "wrong-scheme", "wrong-path",
    "native-cookie", "native-origin", "invalid-header", "bad-token",
])
def test_denial_happens_before_accept_or_any_frame(registry, mutation):
    boundary, ws, _ = setup(registry)
    h = ws.scope["headers"]
    if mutation == "anonymous":
        h.pop()
    elif mutation == "host":
        h[0] = (b"host", b"evil.test")
    elif mutation == "cross-origin":
        h.append((b"origin", b"https://evil.test"))
    elif mutation in {"forwarded", "x-forwarded-host"}:
        h.append((mutation.encode(), b"hub.test:8443"))
    elif mutation == "query":
        ws.scope["query_string"] = b"token=synthetic"
    elif mutation == "duplicate-host":
        h.append(h[0])
    elif mutation == "subprotocol":
        h.append((b"sec-websocket-protocol", b"bearer.synthetic"))
    elif mutation == "wrong-scheme":
        ws.scope["scheme"] = "ws"
    elif mutation == "wrong-path":
        ws.scope["path"] = "/ws/"
    elif mutation == "native-cookie":
        h.append((b"cookie", b"session=synthetic"))
    elif mutation == "native-origin":
        h.append((b"origin", b"https://hub.test:8443"))
    elif mutation == "invalid-header":
        h.append((b"origin", b"\xff"))
    elif mutation == "bad-token":
        h[-1] = (b"authorization", b"Bearer malformed")
    assert run(boundary.admit(ws)) is False
    ws.accept.assert_not_awaited()
    ws.send_text.assert_not_awaited()
    ws.close.assert_awaited()


@pytest.mark.parametrize("profile", ["owner_browser", "kiosk"])
def test_cookie_issuance_is_explicit_gate_even_for_valid_credential(registry, profile):
    boundary, ws, _ = setup(registry, profile)
    assert not run(boundary.admit(ws))
    ws.accept.assert_not_awaited()


def test_http_loopback_kiosk_configuration_does_not_fake_secure_cookie_bootstrap(registry):
    store, cap, _ = registry
    enrolled = store.enroll("kiosk", capability=cap)
    boundary = AuthenticatedBoundary(TrustedAsyncAuthorizer(store._async_authorize), [Endpoint("http://127.0.0.1:8000", "kiosk")],
                                     browser_issuer_ready=True)
    ws = Socket([("host", "127.0.0.1:8000"), ("origin", "http://127.0.0.1:8000"),
                 ("cookie", f"__Host-homehub_ws={enrolled.token}")], scheme="ws")
    assert not run(boundary.admit(ws))


@pytest.mark.parametrize("mutation", ["authorization", "origin", "duplicate-cookie", "missing"])
def test_browser_accepts_only_exact_origin_and_unambiguous_cookie(registry, mutation):
    boundary, ws, enrolled = setup(registry, "owner_browser", browser_issuer_ready=True)
    if mutation == "authorization":
        ws.scope["headers"].append((b"authorization", f"Bearer {enrolled.token}".encode()))
    elif mutation == "origin":
        ws.scope["headers"][1] = (b"origin", b"https://evil.test")
    elif mutation == "duplicate-cookie":
        ws.scope["headers"][-1] = (b"cookie", (
            f"__Host-homehub_ws={enrolled.token}; __Host-homehub_ws={enrolled.token}"
        ).encode())
    else:
        ws.scope["headers"].pop()
    assert not run(boundary.admit(ws))
    ws.accept.assert_not_awaited()


def test_wrong_registry_profile_or_lane_cannot_select_grants(registry):
    boundary, ws, _ = setup(registry)
    boundary._endpoints = (Endpoint("https://hub.test:8443", "desktop_notifier"),)
    assert not run(boundary.admit(ws))
    ws.accept.assert_not_awaited()
    # Shared native host supports both server-fixed lanes, chosen by credential.
    boundary, ws, _ = setup(registry, "desktop_notifier")
    boundary._endpoints = (Endpoint("https://hub.test:8443", "windows_desktop"),
                           Endpoint("https://hub.test:8443", "desktop_notifier"))
    async def scenario():
        assert await boundary.admit(ws)
        assert await boundary.send(ws, "notification", {"title": "Hi"})
        assert not await boundary.send(ws, "mode_update", {"mode": "Home"})
    run(scenario())
    assert ws.frames[0]["data"]["actions"] == []


@pytest.mark.parametrize("profile", ["windows_desktop", "desktop_notifier", "owner_browser", "kiosk"])
def test_initial_direct_broadcast_all_project_and_never_fall_through(registry, profile):
    boundary, ws, _ = setup(registry, profile, browser_issuer_ready=True)
    private = {"room": "PRIVATE", "actions": [{"url": "PRIVATE"}], "title": "Hi",
               "mode": "Home", "time_period": "evening", "hue": True, "sonos": False,
               "build_id": "synthetic", "reason": "validation", "details": "PRIVATE"}
    async def scenario():
        assert await boundary.admit(ws)
        for method in (boundary.initial,):
            await method(ws, [("presence_update", private), ("mode_update", private)])
        await boundary.send(ws, "connection_status", private)
        await boundary.broadcast("notification", private)
        await boundary.broadcast("secret", private)
        await boundary.send(ws, "error", private)
    run(scenario())
    assert "PRIVATE" not in repr(ws.frames)
    expected = {"windows_desktop": ["mode_update"], "desktop_notifier": ["notification"],
                "owner_browser": ["mode_update", "connection_status", "error"],
                "kiosk": ["mode_update", "connection_status", "error"]}
    assert [frame["type"] for frame in ws.frames] == expected[profile]


@pytest.mark.parametrize("cause", ["principal", "credential", "expiry", "rotation"])
@pytest.mark.parametrize("path", ["initial", "direct", "broadcast", "inbound"])
def test_long_session_revalidates_every_path_and_terminates(registry, cause, path):
    store, cap, now = registry
    dispatch = AsyncMock()
    boundary, ws, enrolled = setup(registry, "owner_browser", browser_issuer_ready=True,
                                    dispatcher=dispatch)
    async def scenario():
        assert await boundary.admit(ws)
        assert await boundary.send(ws, "mode_update", {"mode": "Home"})
        if cause == "principal":
            store.revoke(enrolled.principal_id, capability=cap)
        elif cause == "credential":
            store.revoke_credential(enrolled.credential_id, capability=cap)
        elif cause == "rotation":
            store.rotate(enrolled.principal_id, capability=cap, overlap=0)
        else:
            now[0] += 60
        if path == "initial":
            await boundary.initial(ws, [("mode_update", {"mode": "Sleeping"})])
        elif path == "direct":
            assert not await boundary.send(ws, "mode_update", {"mode": "Sleeping"})
        elif path == "broadcast":
            await boundary.broadcast("mode_update", {"mode": "Sleeping"})
        else:
            assert not await boundary.inbound(ws, '{"type":"sonos_command","data":{"action":"pause"}}')
    run(scenario())
    assert len(ws.frames) == 1
    assert not boundary._sessions
    dispatch.assert_not_awaited()
    ws.close.assert_awaited()


@pytest.mark.parametrize("profile", ["owner_browser", "kiosk"])
@pytest.mark.parametrize("kind,data,operation", [
    ("light_command", {"light_id": "1", "bri": 80}, WS_LIGHT_COMMAND),
    ("sonos_command", {"action": "pause"}, WS_SONOS_COMMAND),
])
def test_dispatch_gets_validated_command_and_server_identity_with_exact_operation(
        registry, profile, kind, data, operation, monkeypatch):
    store, _, _ = registry
    calls = []
    original = store._async_authorize
    async def recorded(token, op, **kwargs):
        calls.append((op, kwargs))
        return await original(token, op, **kwargs)
    monkeypatch.setattr(store, "_async_authorize", recorded)
    dispatch = AsyncMock()
    boundary, ws, _ = setup(registry, profile, browser_issuer_ready=True, dispatcher=dispatch)
    async def scenario():
        assert await boundary.admit(ws)
        assert await boundary.inbound(ws, json.dumps({"type": kind, "data": data}))
    run(scenario())
    assert [op for op, _ in calls] == [WS, operation]
    identity, command = dispatch.call_args.args
    assert identity.profile == profile
    assert identity.lane == ("browser" if profile == "owner_browser" else "display")
    assert command.type == kind


@pytest.mark.parametrize("raw", [
    "{broken", "null", "[]", "1", '"light_command"',
    '{"type":"unknown","data":{}}',
    '{"type":"light_command","owner":true,"data":{"light_id":"1","on":true}}',
    '{"type":"light_command","data":{"light_id":"1","on":true,"lane":"browser"}}',
    '{"type":"light_command","data":{"light_id":"1","ct":250,"hue":100}}',
    '{"type":"sonos_command","data":{"action":"volume","volume":999}}',
    '{"type":"sonos_command","type":"light_command","data":{"light_id":"1","on":true}}',
    "x" * 4097, b"binary",
])
def test_malformed_and_false_owner_fields_never_dispatch_or_echo(registry, raw):
    dispatch = AsyncMock()
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True,
                            dispatcher=dispatch)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, raw)
    run(scenario())
    dispatch.assert_not_awaited()
    assert ws.frames == [{"type": "error", "data": {"reason": "validation"}}]


def test_native_cannot_command_or_impersonate_owner(registry):
    dispatch = AsyncMock()
    boundary, ws, _ = setup(registry, dispatcher=dispatch)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, '{"type":"light_command","data":{"light_id":"1","on":true}}')
    run(scenario())
    assert not boundary._sessions
    dispatch.assert_not_awaited()


def test_no_dispatcher_is_fail_closed(registry):
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, '{"type":"sonos_command","data":{"action":"pause"}}')
    run(scenario())
    assert ws.frames == [{"type": "error", "data": {"reason": "unavailable"}}]


def test_cross_socket_and_foreign_adapter_cannot_reuse_session(registry):
    boundary, owner, _ = setup(registry, "owner_browser", browser_issuer_ready=True)
    other = Socket([])
    foreign, _, _ = setup(registry)
    async def scenario():
        assert await boundary.admit(owner)
        assert not await boundary.send(other, "mode_update", {"mode": "Home"})
        assert not await foreign.send(owner, "mode_update", {"mode": "Home"})
        assert not await boundary.inbound(other, '{"type":"sonos_command","data":{"action":"pause"}}')
    run(scenario())
    other.send_text.assert_not_awaited()
    owner.send_text.assert_not_awaited()


def test_admission_and_inbound_resource_budgets(registry):
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True,
                            auth_per_second=1, inbound_per_second=1)
    async def scenario():
        assert await boundary.admit(ws)
        # Admission rate never consumes an established session's budget.
        assert await boundary.send(ws, "mode_update", {"mode": "Home"})
    run(scenario())
    assert boundary.auth_count == 2
    assert ws in boundary._sessions
    boundary, ws, _ = setup(registry, inbound_per_second=1)
    async def flood():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, "bad")
        assert not await boundary.inbound(ws, "bad")
    run(flood())
    assert not boundary._sessions


def test_capacity_and_pre_accept_timeout(registry):
    boundary, ws, _ = setup(registry, max_sessions=1, io_timeout=0.01)
    async def stall():
        await asyncio.Event().wait()
    ws.accept.side_effect = stall
    assert not run(boundary.admit(ws))
    assert not boundary._sessions
    boundary, ws, _ = setup(registry, max_sessions=1)
    other = Socket([])
    other.scope = dict(ws.scope)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.admit(other)
    run(scenario())
    other.accept.assert_not_awaited()


def test_stalled_send_does_not_block_other_socket_and_is_removed(registry):
    store, cap, _ = registry
    enrolled = store.enroll("windows_desktop", capability=cap)
    boundary = AuthenticatedBoundary(TrustedAsyncAuthorizer(store._async_authorize), [Endpoint("https://hub.test", "windows_desktop")],
                                     io_timeout=0.02)
    headers = [("host", "hub.test"), ("authorization", f"Bearer {enrolled.token}")]
    slow, fast = Socket(headers), Socket(headers)
    async def stall(*args):
        await asyncio.Event().wait()
    slow.send_text.side_effect = stall
    async def scenario():
        assert await boundary.admit(slow)
        assert await boundary.admit(fast)
        await boundary.broadcast("mode_update", {"mode": "Home"})
        assert slow not in boundary._sessions
        assert fast in boundary._sessions
    run(scenario())
    assert fast.frames == [{"type": "mode_update", "data": {"mode": "Home"}}]


def test_idle_session_revocation_and_receive_failure_cleanup(registry):
    store, cap, _ = registry
    boundary, ws, enrolled = setup(registry, recheck_seconds=0.01)
    async def receive():
        store.revoke_credential(enrolled.credential_id, capability=cap)
        await asyncio.Event().wait()
    ws.receive_text.side_effect = receive
    run(boundary.serve(ws))
    assert not boundary._sessions
    ws.close.assert_awaited()
    boundary, ws, _ = setup(registry)
    ws.receive_text.side_effect = RuntimeError("synthetic disconnect")
    run(boundary.serve(ws))
    assert not boundary._sessions


def test_store_failure_denies(registry, monkeypatch):
    store, _, _ = registry
    boundary, ws, _ = setup(registry)
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic DB unavailable")
    boundary._store = TrustedAsyncAuthorizer(fail)
    assert not run(boundary.admit(ws))
    ws.accept.assert_not_awaited()
    assert boundary.auth_count == 1
    assert boundary.auth_max_seconds >= 0


def test_measured_over_budget_authorization_denies_without_caching(registry, monkeypatch):
    boundary, ws, _ = setup(registry)
    measurements = iter([10.0, 13.0])
    monkeypatch.setattr("backend.services.ws_authenticated_boundary.time.perf_counter",
                        lambda: next(measurements))
    assert not run(boundary.admit(ws))
    assert boundary.auth_max_seconds == 3.0
    ws.accept.assert_not_awaited()


@pytest.mark.parametrize("phase", ["accept", "send"])
def test_cancellation_erases_session_and_closes_socket(registry, phase):
    boundary, ws, _ = setup(registry)
    async def cancelled(*args):
        raise asyncio.CancelledError
    async def scenario():
        if phase == "accept":
            ws.accept.side_effect = cancelled
            with pytest.raises(asyncio.CancelledError):
                await boundary.admit(ws)
        else:
            assert await boundary.admit(ws)
            ws.send_text.side_effect = cancelled
            with pytest.raises(asyncio.CancelledError):
                await boundary.send(ws, "mode_update", {"mode": "Home"})
        assert not boundary._sessions
    run(scenario())
    ws.close.assert_awaited()


def test_not_ready_socket_cannot_receive_broadcast_during_accept(registry):
    boundary, ws, _ = setup(registry)
    async def accepting():
        await boundary.broadcast("mode_update", {"mode": "Home"})
    ws.accept.side_effect = accepting
    assert run(boundary.admit(ws))
    ws.send_text.assert_not_awaited()


def test_dispatch_timeout_cancels_handler_and_terminates_session(registry):
    cancelled = []
    async def dispatch(identity, command):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True,
                            dispatcher=dispatch, io_timeout=0.01)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, '{"type":"sonos_command","data":{"action":"pause"}}')
        assert not boundary._sessions
    run(scenario())
    assert cancelled == [True]


@pytest.mark.parametrize("cause", ["revoke", "expire", "wrong-secret"])
def test_inactive_or_unverified_credential_cannot_admit(registry, cause):
    store, cap, now = registry
    boundary, ws, enrolled = setup(registry)
    if cause == "revoke":
        store.revoke(enrolled.principal_id, capability=cap)
    elif cause == "expire":
        now[0] += 60
    else:
        ws.scope["headers"][-1] = (
            b"authorization", f"Bearer {enrolled.credential_id}.{'A' * 43}".encode())
    assert not run(boundary.admit(ws))
    ws.accept.assert_not_awaited()


@pytest.mark.parametrize("profile,lane,kind,data", [
    ("owner_browser", "browser", "presence_update", {"room": "private"}),
    ("owner_browser", "display", "mode_update", {"mode": "Home"}),
    ("owner_browser", "browser", "connection_status", {"hue": 1}),
    ("owner_browser", "browser", "error", {"reason": "arbitrary private text"}),
    ("kiosk", "display", "gameday_state", {"private": True}),
])
def test_partial_owner_inventory_denies_unknown_and_malformed(profile, lane, kind, data):
    assert project_event(profile, lane, kind, data) is None


# Correction-pass evidence: admission spam never shares established capacity.
def test_invalid_admission_flood_cannot_evict_valid_session(registry):
    boundary, ws, _ = setup(registry, auth_per_second=8)
    async def scenario():
        assert await boundary.admit(ws)
        for _ in range(16):
            bad = Socket([(k.decode(), v.decode()) for k, v in ws.scope["headers"]])
            bad.scope["headers"][-1] = (b"authorization", f"Bearer {'0' * 32}.{'A' * 43}".encode())
            assert not await boundary.admit(bad)
            bad.accept.assert_not_awaited()
        assert await boundary.send(ws, "mode_update", {"mode": "Home"})
        assert ws in boundary._sessions
        ws.close.assert_not_awaited()
    run(scenario())


def test_unknown_broadcast_flood_uses_no_verifier_or_session_budget(registry):
    boundary, ws, _ = setup(registry)
    async def scenario():
        assert await boundary.admit(ws)
        before = boundary.auth_count
        for _ in range(1000):
            await boundary.broadcast("unreviewed", {"private": "hidden"})
        assert boundary.auth_count == before
        assert await boundary.send(ws, "mode_update", {"mode": "Home"})
        assert ws in boundary._sessions
    run(scenario())
    assert len(ws.frames) == 1


def test_synchronous_verifier_is_refused(registry):
    store, _, _ = registry
    with pytest.raises(TypeError):
        AuthenticatedBoundary(store, [Endpoint("https://hub.test", "windows_desktop")])
    with pytest.raises(TypeError):
        TrustedAsyncAuthorizer(store.authorize)


def test_real_thread_owned_verification_allows_event_loop_progress(registry):
    boundary, ws, _ = setup(registry)
    ticks = []
    async def scenario():
        task = asyncio.create_task(boundary.admit(ws))
        while not task.done():
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.005)
        assert await task
    run(scenario())
    assert len(ticks) >= 3  # real 600k PBKDF, no iteration reduction/mock
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.15


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_cancel_retains_physical_slot_and_discards_late_grant(registry, cancel):
    boundary, ws, _ = setup(registry, auth_seconds=0.01)
    started, release = asyncio.Event(), asyncio.Event()
    original = boundary._store.authorize
    async def delayed(*args, **kwargs):
        identity = await original(*args, **kwargs)
        started.set()
        await release.wait()
        return identity
    boundary._store = TrustedAsyncAuthorizer(delayed)
    async def scenario():
        # Increase deadline to reach a completed real verification before cancel.
        boundary._auth_seconds = 2
        task = asyncio.create_task(boundary.admit(ws))
        await started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            # Timer already owns the 2 second deadline; exercise actual timeout.
            assert not await task
        assert len(boundary._verifications["admission"]) == 1
        other = Socket([])
        other.scope = dict(ws.scope)
        assert not await boundary.admit(other)
        assert boundary.auth_count == 1
        release.set()
        await asyncio.gather(*boundary._verifications["admission"])
        await asyncio.sleep(0)
        assert not boundary._verifications["admission"]
        assert not boundary._sessions
        ws.accept.assert_not_awaited()
        ws.send_text.assert_not_awaited()
    run(scenario())


def test_stalled_admission_does_not_starve_active_verification(registry):
    boundary, ws, _ = setup(registry)
    async def scenario():
        assert await boundary.admit(ws)
        original = boundary._store.authorize
        release = asyncio.Event()
        async def blocked(token, operation, **kwargs):
            if token.startswith("0" * 32):
                await release.wait()
                return None
            return await original(token, operation, **kwargs)
        boundary._store = TrustedAsyncAuthorizer(blocked)
        bad = Socket([(k.decode(), v.decode()) for k, v in ws.scope["headers"]])
        bad.scope["headers"][-1] = (b"authorization", f"Bearer {'0' * 32}.{'A' * 43}".encode())
        task = asyncio.create_task(boundary.admit(bad))
        await asyncio.sleep(0)
        assert await boundary.send(ws, "mode_update", {"mode": "Home"})
        assert ws in boundary._sessions
        release.set()
        assert not await task
    run(scenario())


@pytest.mark.parametrize("data", [
    {"light_id": True, "bri": 10}, {"light_id": 1, "bri": 10},
    {"light_id": "01", "bri": 10}, {"light_id": "7", "bri": 10},
    {"light_id": "1" * 4000, "bri": 10}, {"light_id": "1", "bri": True},
    {"light_id": "1", "bri": "10"}, {"light_id": "1", "bri": 10.0},
    {"light_id": "1", "on": "yes"}, {"light_id": "1", "on": 1},
    {"light_id": "1", "ct": 152}, {"light_id": "1", "ct": 501},
    {"light_id": "1", "hue": 65536}, {"light_id": "1", "sat": 255},
    {"light_id": "1", "bri": -1}, {"light_id": "1", "bri": 255},
    {"light_id": "1", "transitiontime": -1}, {"light_id": "1", "transitiontime": 601},
    {"light_id": "1", "transitiontime": True}, {"light_id": "1", "ct": 250, "sat": 10},
    {"light_id": "1", "bri": 10, "command_id": "x" * 4000},
    {"light_id": "1", "on": None}, {"light_id": "1", "bri": None},
])
def test_strict_inbound_scalars_never_dispatch(registry, data):
    dispatch = AsyncMock()
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True, dispatcher=dispatch)
    async def scenario():
        assert await boundary.admit(ws)
        assert not await boundary.inbound(ws, json.dumps({"type": "light_command", "data": data}))
    run(scenario())
    dispatch.assert_not_awaited()
    assert ws.frames == [{"type": "error", "data": {"reason": "validation"}}]


@pytest.mark.parametrize("identifier", list("123456"))
def test_registered_lights_and_legitimate_svelte_command_remain_valid(identifier):
    from backend.services.ws_authenticated_boundary import _strict_command
    from backend.services.light_state_calculator import ALL_LIGHT_IDS
    assert set(ALL_LIGHT_IDS) == set("123456")
    command = _strict_command({"type": "light_command", "data": {
        "light_id": identifier, "on": True, "bri": 254, "ct": 153, "transitiontime": 600}})
    assert command.data.light_id == identifier


# Representative synthetic fields copied from the actual emitters and stores.
_RELEASE_EVENTS = [
    ("mode_update", {"mode": "relax", "source": "physical", "manual_override": False,
                     "house_state": "home", "activity": "relax", "time_period": "evening",
                     "override_source": None, "override_user_owned": False}),
    ("light_update", {"light_id": "6", "name": "Plant Wash", "on": True, "bri": 120,
                      "hue": 100, "sat": 20, "ct": 250, "colormode": "ct", "reachable": True}),
    ("sonos_update", {"state": "PLAYING", "track": "Synthetic", "artist": "Test", "album": "Test",
                      "volume": 20, "mute": False}),
    ("dnd_update", {"enabled": True, "expiry_utc": None, "minutes_remaining": 120}),
    ("music_suggestion", {"mode": "relax", "title": "Test", "vibe": None, "message": "Play Test?"}),
    ("music_auto_played", {"mode": "relax", "title": "Test", "vibe": "calm"}),
    ("mode_suggestion", {"suggestion_id": 1, "rule_id": 2, "predicted_mode": "relax",
                         "confidence": 80, "sample_count": 10, "message": "Try relax"}),
    ("mode_suggestion_dismissed", {}),
    ("brightness_suggestion", {"id": 1, "kind": "brightness", "payload": {
        "light_id": "1", "mode": "relax", "period": "evening", "weather_class": None,
        "suggested_bri": 100, "suggested_multiplier": 1.2, "sample_count": 6, "distinct_days": 3},
        "status": "pending", "fired_at": "2026-11-14T12:00:00Z", "confidence": 80, "sample_count": 6}),
    ("brightness_suggestion_dismissed", {"id": 1}),
    ("ambient_update", {"playing": False, "sound": None, "sound_label": None, "volume": 0.3,
                        "source": None, "weather_override": False, "weather_reactive": True,
                        "sonos_enabled": True, "sonos_ambient_active": False, "sonos_ambient_pending": False}),
    ("camera_update", {"detection": "unknown", "detection_source": "latitude", "confidence": 0.5,
                       "ambient_lux": 10, "ema_lux": 12.5, "zone": None, "posture": None}),
    ("gameday_state", {"status": "in-progress", "opponent": "Test", "kickoff_utc": None,
                       "score_colts": 7, "score_opp": 0, "quarter": 1, "clock": "8:00",
                       "possession": "colts", "last_play": None,
                       "current_drive": {"team": "colts", "plays": 5, "yards": 40, "elapsed": "2:30"}}),
    ("gameday_viewer_state", {"status": "no-game"}),
    ("gameday_viewer_sync", {"enabled": True, "active": False, "authoritative": False,
                            "presentation_active": False, "reason": "new_session", "program_time_offset_seconds": 0}),
    ("gameday_play", {"timestamp": "2026-11-14T12:00:00Z", "play_type": "touchdown",
                      "description": "Test touchdown", "player": None, "kicker": None,
                      "yards": 20, "scoring_team": "colts", "wpa": 0.1}),
    ("gameday_celebration", {"sequence_key": "colts_td", "started_at": 1794657600.0}),
]


@pytest.mark.parametrize("profile,lane", [("owner_browser", "browser"), ("kiosk", "display")])
@pytest.mark.parametrize("kind,data", _RELEASE_EVENTS)
def test_release_projections_preserve_consumed_fields_and_strip_unknowns(profile, lane, kind, data):
    import copy
    injected = copy.deepcopy(data)
    injected["private"] = {"secret": "PRIVATE"}
    for value in injected.values():
        if type(value) is dict:
            value["private"] = "PRIVATE"
    result = project_event(profile, lane, kind, injected)
    assert result == {"type": kind, "data": data}
    assert "PRIVATE" not in repr(result)
    for native_profile, native_lane in [("windows_desktop", "display"), ("desktop_notifier", "notifier")]:
        result = project_event(native_profile, native_lane, kind, injected)
        if result is not None:
            assert kind == "mode_update"
            assert set(result["data"]) <= {"mode", "time_period"}


@pytest.mark.parametrize("kind,data", [
    ("light_update", {"light_id": "1", "bri": True}),
    ("mode_update", {"mode": "home", "manual_override": "yes"}),
    ("gameday_state", {"status": "in-progress", "last_play": {"yards": True}}),
    ("gameday_state", {"status": "in-progress", "current_drive": {"plays": "5"}}),
    ("gameday_viewer_sync", {"active": 1}),
    ("camera_update", {"confidence": float("nan")}),
    ("music_suggestion", {"title": "x" * 601}),
    ("brightness_suggestion", {"payload": {"suggested_bri": 255}}),
    ("pipeline_state", {"inputs": {"private": True}}),
    ("light_command_result", {"command_id": "unreviewed"}),
    ("light_command_reconciliation", {"command_id": "unreviewed"}),
])
def test_bounded_nested_projections_and_unimplemented_contracts_deny(kind, data):
    assert project_event("owner_browser", "browser", kind, data) is None


@pytest.mark.parametrize("cause", ["revocation", "expiry"])
def test_thread_owned_verifier_rechecks_changes_during_hash(registry, monkeypatch, cause):
    import hashlib
    import threading
    store, cap, now = registry
    boundary, ws, enrolled = setup(registry)
    hashed, release = threading.Event(), threading.Event()
    original = hashlib.pbkdf2_hmac
    def held_hash(*args, **kwargs):
        result = original(*args, **kwargs)
        hashed.set()
        if not release.wait(3):
            raise RuntimeError("synthetic test deadline")
        return result
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", held_hash)
    async def scenario():
        task = asyncio.create_task(boundary.admit(ws))
        try:
            async with asyncio.timeout(2):
                while not hashed.is_set():
                    await asyncio.sleep(0.005)
            if cause == "revocation":
                store.revoke_credential(enrolled.credential_id, capability=cap)
            else:
                now[0] += 60
        finally:
            release.set()
        assert not await task
        ws.accept.assert_not_awaited()
    run(scenario())


def test_parallel_close_wins_over_pending_send_authorization(registry):
    boundary, ws, _ = setup(registry)
    async def scenario():
        assert await boundary.admit(ws)
        started, release = asyncio.Event(), asyncio.Event()
        original = boundary._store.authorize
        async def pending(*args, **kwargs):
            started.set()
            await release.wait()
            return await original(*args, **kwargs)
        boundary._store = TrustedAsyncAuthorizer(pending)
        task = asyncio.create_task(boundary.send(ws, "mode_update", {"mode": "Home"}))
        await started.wait()
        await boundary.close(ws)
        release.set()
        assert not await task
        ws.send_text.assert_not_awaited()
    run(scenario())


def test_command_authorization_cancellation_erases_session(registry):
    boundary, ws, _ = setup(registry, "owner_browser", browser_issuer_ready=True)
    async def scenario():
        assert await boundary.admit(ws)
        entered, release = asyncio.Event(), asyncio.Event()
        async def pending(*args, **kwargs):
            entered.set()
            await release.wait()
            return None
        boundary._store = TrustedAsyncAuthorizer(pending)
        task = asyncio.create_task(boundary.inbound(ws, '{"type":"sonos_command","data":{"action":"pause"}}'))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not boundary._sessions
        assert len(boundary._verifications["active"]) == 1
        release.set()
        await asyncio.gather(*boundary._verifications["active"])
    run(scenario())


@pytest.mark.parametrize("identifier", ["", "short", "x" * 128, "x" * 129, "x" * 4000])
def test_unimplemented_command_correlation_is_never_silently_accepted(identifier):
    from backend.services.ws_authenticated_boundary import _strict_command
    from pydantic import ValidationError
    for placement in ("envelope", "data"):
        message = {"type": "light_command", "data": {"light_id": "1", "on": True}}
        (message if placement == "envelope" else message["data"])["command_id"] = identifier
        with pytest.raises(ValidationError):
            _strict_command(message)


def test_actual_nullable_hue_colormode_is_preserved():
    assert project_event("owner_browser", "browser", "light_update", {
        "light_id": "6", "ct": None, "colormode": None}) == {
            "type": "light_update", "data": {"light_id": "6", "ct": None, "colormode": None}}


@pytest.mark.parametrize("profile,lane", [
    ("owner_browser", "browser"), ("kiosk", "display"),
])
def test_guarded_lighting_receipts_project_privately_without_stale_observation(profile, lane):
    command_id = "a" * 32
    result = project_event(profile, lane, "light_command_result", {
        "command_id": command_id, "light_id": "2", "status": "denied",
        "debug": {"private": "never-visible"},
    })
    assert result == {"type": "light_command_result", "data": {
        "command_id": command_id, "light_id": "2", "status": "denied",
    }}

    result = project_event(profile, lane, "light_command_result", {
        "command_id": command_id, "status": "invalid",
    })
    assert result == {"type": "light_command_result", "data": {
        "command_id": command_id, "status": "invalid",
    }}

    advisory = project_event(profile, lane, "light_command_reconciliation", {
        "command_id": None, "light_id": "2",
        "observation": {"reachable": True, "private_field": "stale-or-sensitive"},
    })
    assert advisory == {"type": "light_command_reconciliation", "data": {
        "command_id": None, "light_id": "2",
    }}
    assert "observation" not in json.dumps(advisory)


@pytest.mark.parametrize("kind,data", [
    ("light_command_result", {"command_id": "bad", "light_id": "2", "status": "denied"}),
    ("light_command_result", {"command_id": "a" * 32, "light_id": "9", "status": "denied"}),
    ("light_command_result", {"command_id": "a" * 32, "status": "accepted"}),
    ("light_command_result", {"command_id": "a" * 32}),
    ("light_command_reconciliation", {"light_id": 2, "command_id": None}),
])
def test_guarded_lighting_receipts_fail_closed_on_invalid_fields(kind, data):
    assert project_event("owner_browser", "browser", kind, data) is None


def test_native_subscription_never_receives_owner_lighting_receipts():
    assert project_event("windows_desktop", "display", "light_command_result", {
        "command_id": "a" * 32, "light_id": "2", "status": "acknowledged",
    }) is None
    assert project_event("desktop_notifier", "notifier", "light_command_reconciliation", {
        "command_id": None, "light_id": "2",
    }) is None
