from __future__ import annotations

from starlette.requests import Request

from backend.api.routes.automation import get_activity
from backend.services.automation_engine import AutomationEngine


def _request(engine: AutomationEngine) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/automation/activity",
        "raw_path": b"/api/automation/activity",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    request = Request(scope)

    class State:
        automation = engine

    class App:
        state = State()

    request.scope["app"] = App()
    return request


async def test_get_activity_projects_internal_idle_to_home_general(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = AutomationEngine(
        hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
    )
    engine._mode_source = "audio_ml"

    result = await get_activity(_request(engine))

    assert result["mode"] == "general"
    assert result["source"] == "time_of_day"
    assert result["house_state"] == "home"
    assert result["activity"] == "general"
    assert result["detected_mode"] == "idle"
    assert result["detected_source"] == "audio_ml"


async def test_get_activity_keeps_sleeping_lifecycle_visible(
    mock_hue, mock_hue_v2, mock_ws,
):
    engine = AutomationEngine(
        hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws,
    )
    engine._manual_override = True
    engine._override_mode = "sleeping"
    engine._override_source = "api:test"

    result = await get_activity(_request(engine))

    assert result["mode"] == "sleeping"
    assert result["house_state"] == "sleeping"
    assert result["activity"] is None
    assert result["detected_mode"] == "idle"
