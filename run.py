#!/usr/bin/env python3
"""
Home Hub — Single entry point.

Usage:
    python run.py
"""
import uvicorn

from backend.config import settings


def main() -> None:
    """Start the Home Hub server."""
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
