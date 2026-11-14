"""Single authenticated WebSocket runtime; unconfigured startup is fail closed.

Producers retain broadcast, but never acquire sockets or a raw send path.
Only trusted application composition may supply configuration. No environment,
HTTP request, private address or same-process IdentityStore enables admission.
"""
import asyncio
from dataclasses import dataclass

from backend.services.ws_authenticated_boundary import (
    AuthenticatedBoundary, Endpoint, TrustedAsyncAuthorizer,
)


@dataclass(frozen=True)
class WebSocketRuntimeConfiguration:
    """Source seam, NOT evidence of a provisioned broker or session issuer.

    The callback must verify afresh through the separately protected authority,
    reserve independent admission/active capacity and own nonblocking cleanup.
    browser_issuer_ready asserts separately reviewed secure session delivery.
    There is intentionally no default verifier or production endpoint.
    """

    authorizer: TrustedAsyncAuthorizer
    endpoints: tuple[Endpoint, ...]
    browser_issuer_ready: bool = False


class WebSocketManager:
    def __init__(self, *, configuration=None, dispatcher=None):
        if configuration is not None and type(configuration) is not WebSocketRuntimeConfiguration:
            raise TypeError("Explicit trusted WebSocket runtime configuration required")
        self._boundary = None if configuration is None else AuthenticatedBoundary(
            configuration.authorizer, configuration.endpoints,
            browser_issuer_ready=configuration.browser_issuer_ready,
            dispatcher=dispatcher,
        )

    async def serve(self, websocket, initial=()):
        if self._boundary is None:
            # Before accept AND before evaluating the snapshot callback.
            try:
                await asyncio.wait_for(websocket.close(code=1008), 2.0)
            except Exception:
                pass
            return
        await self._boundary.serve(websocket, initial)

    async def broadcast(self, message_type, data):
        if self._boundary is not None:
            await self._boundary.broadcast(message_type, data)

    @property
    def connection_count(self):
        return self._boundary.connection_count if self._boundary is not None else 0

    @property
    def light_command_results(self):
        return self._boundary is not None and self._boundary._dispatcher is not None
