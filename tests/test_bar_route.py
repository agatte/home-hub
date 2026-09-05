from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.bar import get_bar_status


def _request(hostname: str, app_url: str):
    service = SimpleNamespace(
        app_url=app_url,
        get_status=AsyncMock(return_value={"total_bottles": 30}),
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(bar_service=service)),
        url=SimpleNamespace(hostname=hostname),
    )


@pytest.mark.asyncio
async def test_bar_status_rewrites_loopback_url_for_remote_browser() -> None:
    body = await get_bar_status(_request("192.168.86.210", "http://localhost:8001"))
    assert body["bar_app_url"] == "http://192.168.86.210:8001"


@pytest.mark.asyncio
async def test_bar_status_keeps_loopback_for_local_kiosk() -> None:
    body = await get_bar_status(_request("localhost", "http://localhost:8001"))
    assert body["bar_app_url"] == "http://localhost:8001"


@pytest.mark.asyncio
async def test_bar_status_preserves_non_loopback_app_url() -> None:
    body = await get_bar_status(_request("192.168.86.210", "https://bar.example.test/app"))
    assert body["bar_app_url"] == "https://bar.example.test/app"
