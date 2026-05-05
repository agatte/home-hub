"""Tests for ``CameraService._update_ema_lux`` stale-reset behavior.

The EMA blends incoming lux readings (α=0.3) but should snap to the raw
value when the last update was longer than ``LUX_EMA_STALE_RESET_SECONDS``
ago — protects against a multi-hour sleeping pause leaving yesterday's
room light averaged with this morning's first frame.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from backend.services.camera_service import (
    LUX_EMA_ALPHA,
    LUX_EMA_STALE_RESET_SECONDS,
    CameraService,
)


def _make_service() -> CameraService:
    return CameraService(
        ws_manager=AsyncMock(), automation_engine=AsyncMock(), ml_logger=AsyncMock(),
    )


def test_update_ema_lux_initializes_on_first_call() -> None:
    svc = _make_service()
    assert svc._ema_lux is None
    svc._update_ema_lux(120.0)
    assert svc._ema_lux == 120.0


def test_update_ema_lux_blends_when_recent() -> None:
    svc = _make_service()
    svc._update_ema_lux(100.0)
    svc._update_ema_lux(200.0)
    expected = LUX_EMA_ALPHA * 200.0 + (1 - LUX_EMA_ALPHA) * 100.0
    assert svc._ema_lux == pytest.approx(expected)


def test_update_ema_lux_resets_when_stale() -> None:
    """A reading after the stale window should snap, not blend."""
    svc = _make_service()
    svc._update_ema_lux(100.0)
    # Backdate the last-update timestamp past the stale window.
    svc._last_lux_update = (
        datetime.now(timezone.utc)
        - timedelta(seconds=LUX_EMA_STALE_RESET_SECONDS + 1)
    )
    svc._update_ema_lux(50.0)
    # Snap, not blend (blend would be 0.3*50 + 0.7*100 = 85.0).
    assert svc._ema_lux == 50.0


def test_update_ema_lux_blends_inside_stale_window() -> None:
    """A reading just inside the stale window should still blend."""
    svc = _make_service()
    svc._update_ema_lux(100.0)
    svc._last_lux_update = (
        datetime.now(timezone.utc)
        - timedelta(seconds=LUX_EMA_STALE_RESET_SECONDS - 5)
    )
    svc._update_ema_lux(50.0)
    expected = LUX_EMA_ALPHA * 50.0 + (1 - LUX_EMA_ALPHA) * 100.0
    assert svc._ema_lux == pytest.approx(expected)
