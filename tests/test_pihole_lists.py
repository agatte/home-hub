"""Focused Pi-hole v6 blocklist deletion coverage (#228)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from backend.api.routes.pihole import delete_blocklist
from backend.services.pihole_service import (
    PiholeApiError,
    PiholeService,
    PiholeUnreachableError,
)


def _service() -> PiholeService:
    return PiholeService("http://localhost:8080", "test-pass")


def _client(response):
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_delete_blocklist_supplies_required_v6_block_type():
    svc = _service()
    svc._sid = "test-sid"
    response = MagicMock()
    response.status_code = 204
    response.content = b""
    response.raise_for_status = MagicMock()
    client = _client(response)

    with patch(
        "backend.services.pihole_service.httpx.AsyncClient",
        return_value=client,
    ):
        assert await svc.delete_blocklist("https://example.com/list.txt") is True

    request = client.request.await_args
    assert request.args[0] == "DELETE"
    assert request.args[1].endswith(
        "/api/lists/https%3A%2F%2Fexample.com%2Flist.txt"
    )
    assert request.kwargs["params"] == {"type": "block"}


@pytest.mark.asyncio
async def test_http_contract_error_is_reachable_api_failure_not_outage():
    svc = _service()
    svc._sid = "test-sid"
    request = httpx.Request("DELETE", "http://localhost:8080/api/lists/x")
    response = httpx.Response(400, request=request, json={"error": "bad request"})
    client = _client(response)

    with patch(
        "backend.services.pihole_service.httpx.AsyncClient",
        return_value=client,
    ):
        with pytest.raises(PiholeApiError) as exc_info:
            await svc._request("DELETE", "/api/lists/x")

    assert exc_info.value.status_code == 400
    assert svc.connected is True
    assert svc._unreachable_logged is False


def _request_with_service(service):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pihole_service=service)),
    )


@pytest.mark.asyncio
async def test_delete_route_maps_pihole_api_rejection_to_502():
    error = PiholeApiError("DELETE", "/api/lists/x", 400)
    service = SimpleNamespace(delete_blocklist=AsyncMock(side_effect=error))
    request = _request_with_service(service)

    with pytest.raises(HTTPException) as exc_info:
        await delete_blocklist("https%3A%2F%2Fexample.com%2Flist.txt", request)
    assert exc_info.value.status_code == 502
    assert "request failed" in exc_info.value.detail.lower()
    service.delete_blocklist.assert_awaited_once_with(
        "https://example.com/list.txt"
    )


@pytest.mark.asyncio
async def test_delete_route_keeps_true_unreachable_failure_at_503():
    error = PiholeUnreachableError("network unavailable")
    service = SimpleNamespace(delete_blocklist=AsyncMock(side_effect=error))
    request = _request_with_service(service)

    with pytest.raises(HTTPException) as exc_info:
        await delete_blocklist("https%3A%2F%2Fexample.com%2Flist.txt", request)

    assert exc_info.value.status_code == 503
    assert "unreachable" in exc_info.value.detail.lower()
