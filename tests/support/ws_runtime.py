"""Synthetic /ws composition only: no issuer, registry or real transport."""
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.identity_core import Identity
from backend.identity_policy import PROFILES
from backend.services.websocket_manager import WebSocketManager, WebSocketRuntimeConfiguration
from backend.services.ws_authenticated_boundary import Endpoint, TrustedAsyncAuthorizer

TOKEN = "0" * 32 + "." + "A" * 43  # fixed, deliberately synthetic


class Socket(SimpleNamespace):
    __hash__ = object.__hash__
    __eq__ = object.__eq__


def configure_runtime(state, socket, profile="owner_browser", authorize=None):
    from backend.main import _dispatch_authenticated_ws_command
    async def synthetic(token, operation, *, lane, stage):
        policy = PROFILES[profile]
        if token == TOKEN and (operation, lane) in policy.grants:
            return Identity("synthetic-principal", profile, policy.source, lane)
        return None
    state.ws_manager = WebSocketManager(
        configuration=WebSocketRuntimeConfiguration(
            TrustedAsyncAuthorizer(authorize or synthetic),
            (Endpoint("https://hub.test", profile),), True),
        dispatcher=partial(_dispatch_authenticated_ws_command, SimpleNamespace(state=state)),
    )
    socket.accept = AsyncMock()
    socket.close = AsyncMock()
    socket.scope = scope(profile)
    return state.ws_manager


def scope(profile="owner_browser"):
    headers = [(b"host", b"hub.test")]
    if profile in {"owner_browser", "kiosk"}:
        headers += [(b"origin", b"https://hub.test"),
                    (b"cookie", ("__Host-homehub_ws=" + TOKEN).encode())]
    else:
        headers += [(b"authorization", ("Bearer " + TOKEN).encode())]
    return {"type": "websocket", "path": "/ws", "scheme": "wss",
            "query_string": b"", "headers": headers}
