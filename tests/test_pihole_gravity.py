"""Focused coverage for explicit Pi-hole gravity refresh."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.pihole import refresh_gravity
from backend.services.pihole_service import PiholeService


def _service() -> PiholeService:
    return PiholeService("http://localhost:8080", "test-pass")


@pytest.mark.asyncio
async def test_service_refresh_gravity_accepts_text_progress_response():
    svc = _service()
    svc._sid = "test-sid"
    response = MagicMock()
    response.status_code = 200
    response.content = b"[i] Building tree..."
    response.text = "[i] Building tree..."
    response.raise_for_status = MagicMock()
    response.json.side_effect = AssertionError("gravity response must not parse JSON")

    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch(
        "backend.services.pihole_service.httpx.AsyncClient",
        return_value=client,
    ) as async_client_cls:
        assert await svc.refresh_gravity() is True

    async_client_cls.assert_called_once_with(timeout=300.0)

    assert svc.connected is True
    client.request.assert_awaited_once()
    _, kwargs = client.request.await_args
    assert kwargs["headers"]["X-FTL-SID"] == "test-sid"


@pytest.mark.asyncio
async def test_route_refresh_gravity_delegates_to_service():
    service = SimpleNamespace(refresh_gravity=AsyncMock(return_value=True))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pihole_service=service)),
    )

    assert await refresh_gravity(request) == {"status": "ok"}
    service.refresh_gravity.assert_awaited_once_with()
