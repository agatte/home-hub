from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from backend.api.auth import require_localhost
from backend.api.routes import presence
from backend.main import app
from backend.services.away_manager import (
    HomeReconciliationIndeterminate,
    HomeReconciliationRejected,
)


def _request(away_manager) -> Request:
    return Request({
        "type": "http", "method": "POST",
        "path": "/api/presence/reconcile-home",
        "headers": [(b"x-source", b"return_home:test")],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8000), "scheme": "http",
        "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(away_manager=away_manager)),
    })


def _manager(*, result=None, error=None):
    manager = SimpleNamespace()
    manager.reconcile_home = AsyncMock(return_value=result, side_effect=error)
    manager.activate_home_reconciliation = AsyncMock(return_value=result, side_effect=error)
    manager.reconciliation_status = AsyncMock()
    manager.run_arrival_effects = AsyncMock()
    return manager


@pytest.mark.asyncio
async def test_prepare_response_does_not_run_arrival_effects():
    manager = _manager(result={
        "outcome": "prepared_home", "resolved": True, "committed": True,
        "reconciliation_id": "return-1",
    })
    result = await presence.reconcile_home(
        presence.HomeReconciliationRequest(reconciliation_id="return-1"),
        _request(manager),
    )
    assert result["committed"] is True
    manager.run_arrival_effects.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_schedules_effects_after_host_publish():
    manager = _manager(result={
        "resolved": True, "committed": True, "activated": True,
        "effects_required": True, "away_minutes": 42,
    })
    background = BackgroundTasks()
    result = await presence.activate_home_reconciliation(
        "return-1", _request(manager), background,
    )
    assert result["activated"] is True
    assert len(background.tasks) == 1


@pytest.mark.parametrize(
    ("error", "status_code", "outcome"),
    [
        (HomeReconciliationRejected("no commit"), 409, "definitive_failure"),
        (HomeReconciliationIndeterminate("mixed"), 503, "indeterminate"),
    ],
)
@pytest.mark.asyncio
async def test_prepare_failure_classification(error, status_code, outcome):
    manager = _manager(error=error)
    with pytest.raises(HTTPException) as raised:
        await presence.reconcile_home(
            presence.HomeReconciliationRequest(reconciliation_id="return-2"),
            _request(manager),
        )
    assert raised.value.status_code == status_code
    assert raised.value.detail["outcome"] == outcome


@pytest.mark.asyncio
async def test_status_requires_resolved_transaction():
    manager = _manager()
    manager.reconciliation_status.return_value = {
        "outcome": "unresolved", "resolved": False,
        "committed": False, "reconciliation_id": "return-3",
    }
    with pytest.raises(HTTPException) as raised:
        await presence.home_reconciliation_status("return-3", _request(manager))
    assert raised.value.status_code == 409


def test_reconciliation_routes_remain_direct_localhost_only():
    routes = {
        route.path: route
        for route in app.routes
        if route.path.startswith("/api/presence/reconcile-home")
    }
    assert set(routes) == {
        "/api/presence/reconcile-home",
        "/api/presence/reconcile-home/{reconciliation_id}",
        "/api/presence/reconcile-home/{reconciliation_id}/activate",
    }
    for route in routes.values():
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert require_localhost in dependency_calls
