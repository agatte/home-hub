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
    )


if __name__ == "__main__":
    main()
