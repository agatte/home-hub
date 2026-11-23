#!/usr/bin/env python3
"""
Home Hub — Single entry point.

Usage:
    python run.py
"""
import asyncio
import copy
import ipaddress
import ssl
from pathlib import Path

import uvicorn

from backend.config import settings


def _tls_context() -> ssl.SSLContext | None:
    """Load the pair once, before either listener binds, without prompting."""
    cert = settings.HOME_HUB_SERVER_TLS_CERTFILE
    key = settings.HOME_HUB_SERVER_TLS_KEYFILE
    if cert is None and key is None:
        return None
    if not cert or not key or not cert.strip() or not key.strip():
        raise ValueError("Direct TLS requires both nonempty certificate and key paths")
    if settings.APP_ENV == "development":
        raise ValueError("Direct TLS does not support development reload")
    _validate_tls_host(settings.HOME_HUB_SERVER_TLS_HOST)
    if not 1 <= settings.HOME_HUB_SERVER_TLS_PORT <= 65535 or settings.HOME_HUB_SERVER_TLS_PORT == 8000:
        raise ValueError("Direct TLS requires a valid port different from 8000")
    try:
        if not Path(cert).is_file() or not Path(key).is_file():
            raise ValueError("Invalid TLS files")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

        def reject_password() -> str:
            raise ValueError("Encrypted TLS keys are not supported")

        context.load_cert_chain(cert, key, password=reject_password)
    except (OSError, ssl.SSLError, ValueError):
        raise ValueError("Direct TLS certificate or key is invalid or unreadable") from None
    return context


def _validate_tls_host(host: str) -> None:
    """Do not add a wildcard or publicly exposed listener by accident."""
    try:
        address = ipaddress.ip_address(host.strip())
    except (ValueError, AttributeError):
        raise ValueError("Direct TLS bind must use an explicit IP address") from None
    # ipaddress.is_private also includes documentation/reserved ranges.
    # Restrict this release slice to literal loopback, RFC1918 or IPv6 ULA;
    # a future routed/Tailscale ingress needs a separate exposure review.
    local_networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    if not address.is_loopback and not any(
        address in ipaddress.ip_network(network) for network in local_networks
    ):
        raise ValueError("Direct TLS bind must be a specific RFC1918, ULA or loopback IP")


class DualTransportServer(uvicorn.Server):
    """One Uvicorn lifecycle and server state, with a second TLS socket."""

    def __init__(self, config, tls_context, tls_host, tls_port):
        if config.reload or config.workers != 1 or config.proxy_headers:
            raise ValueError("Dual transport requires one worker, no reload or proxy headers")
        _validate_tls_host(tls_host)
        if tls_port == config.port or not 1 <= tls_port <= 65535:
            raise ValueError("Direct TLS requires a distinct valid listener")
        super().__init__(config)
        self.tls_context = tls_context
        self.tls_host = tls_host
        self.tls_port = tls_port

    async def startup(self, sockets=None):
        if sockets is not None:
            raise ValueError("Dual transport does not support inherited sockets")
        await super().startup(sockets=sockets)
        if not self.started:
            return
        # Config.is_ssl controls the ASGI scheme in both HTTP and WS protocols.
        # Share the loaded application and lifespan state, changing only TLS.
        secure_config = copy.copy(self.config)
        secure_config.ssl_certfile = "enabled"
        secure_config.ssl = self.tls_context

        def protocol():
            return secure_config.http_protocol_class(
                config=secure_config, server_state=self.server_state,
                app_state=self.lifespan.state,
            )

        try:
            listener = await asyncio.get_running_loop().create_server(
                protocol, host=self.tls_host, port=self.tls_port,
                ssl=self.tls_context, backlog=secure_config.backlog,
            )
        except BaseException as exc:
            # Uvicorn's normal shutdown closes the first socket and drains its
            # connections before terminating the single application lifespan.
            await self.shutdown()
            self.started = False
            if isinstance(exc, Exception):
                raise SystemExit("Direct TLS listener could not bind") from None
            raise
        self.servers.append(listener)


def main() -> None:
    """Start the Home Hub server."""
    context = _tls_context()
    if context is not None:
        config = uvicorn.Config(
            "backend.main:app", host="0.0.0.0", port=8000,
            reload=False, workers=1, proxy_headers=False,
            log_level=settings.LOG_LEVEL.lower(), ws_ping_interval=30, ws_ping_timeout=60,
        )
        DualTransportServer(config, context, settings.HOME_HUB_SERVER_TLS_HOST,
                            settings.HOME_HUB_SERVER_TLS_PORT).run()
        return
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_level=settings.LOG_LEVEL.lower(),
        # Mobile-friendly WS keepalive: uvicorn defaults (20s/20s) close
        # sockets when a phone screen sleeps briefly, triggering the
        # "Reconnecting..." banner. 30s pings + 60s timeout survives a
        # one-minute screen-off without dropping the connection.
        ws_ping_interval=30,
        ws_ping_timeout=60,
    )


if __name__ == "__main__":
    main()
