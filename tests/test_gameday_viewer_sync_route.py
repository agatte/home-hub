from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes.gameday import (
    ViewerClockReport,
    ViewerSyncToggleRequest,
    get_viewer_sync,
    report_viewer_clock,
    set_viewer_sync_enabled,
)


def _request(viewer_sync, host: str = "127.0.0.1", headers: dict | None = None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(gameday_viewer_sync=viewer_sync)),
        client=SimpleNamespace(host=host),
        headers=headers or {},
    )


def _body(method: str = "mpris") -> ViewerClockReport:
    return ViewerClockReport(
        service="hulu",
        player="chromium",
        playback_status="Playing",
        media_timestamp=1789501889.5,
        observed_at=datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc),
        method=method,
    )


@pytest.mark.asyncio
async def test_viewer_clock_ingestion_is_localhost_only():
    viewer_sync = MagicMock()
    viewer_sync.record_sample = AsyncMock(return_value={"ok": True})

    with pytest.raises(HTTPException) as exc:
        await report_viewer_clock(_body(), _request(viewer_sync, host="192.168.1.20"))

    assert exc.value.status_code == 403
    viewer_sync.record_sample.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_clock_ingestion_rejects_tunnel_origin_loopback():
    viewer_sync = MagicMock()
    viewer_sync.record_sample = AsyncMock()
    request = _request(
        viewer_sync,
        headers={"X-Tunnel-Origin": "cloudflare"},
    )

    with pytest.raises(HTTPException) as exc:
        await report_viewer_clock(_body(), request)

    assert exc.value.status_code == 403
    viewer_sync.record_sample.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_clock_ingestion_accepts_local_mpris_and_delegates():
    viewer_sync = MagicMock()
    viewer_sync.record_sample = AsyncMock(return_value={"authoritative": False})
    body = _body()

    result = await report_viewer_clock(body, _request(viewer_sync))

    assert result == {"authoritative": False}
    viewer_sync.record_sample.assert_awaited_once_with(
        service="hulu",
        player="chromium",
        playback_status="Playing",
        media_timestamp=1789501889.5,
        observed_at=body.observed_at,
    )


@pytest.mark.asyncio
async def test_non_mpris_clock_method_is_rejected():
    viewer_sync = MagicMock()
    viewer_sync.record_sample = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await report_viewer_clock(_body(method="dom"), _request(viewer_sync))

    assert exc.value.status_code == 400
    viewer_sync.record_sample.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_and_toggle_delegate_to_viewer_sync_service():
    viewer_sync = MagicMock()
    viewer_sync.snapshot.return_value = {"enabled": True, "authoritative": True}
    viewer_sync.set_enabled = AsyncMock()
    request = _request(viewer_sync)

    assert await get_viewer_sync(request) == {"enabled": True, "authoritative": True}
    result = await set_viewer_sync_enabled(ViewerSyncToggleRequest(enabled=False), request)

    viewer_sync.set_enabled.assert_awaited_once_with(False)
    assert result == {"enabled": True, "authoritative": True}
