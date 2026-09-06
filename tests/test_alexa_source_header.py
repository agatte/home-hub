"""
Tests for the X-Source header → telemetry source flow on write endpoints.

The Alexa lambda passes ``X-Source: alexa:<intent_name>`` on every API
call; the backend's ``source_from_request`` helper (in ``backend.api.auth``)
extracts the header on each write route and threads it into the
``activity_events`` / ``light_adjustments`` / ``sonos_playback_events`` /
``scene_activations`` row's source column. Without the header, routes
fall back to their existing defaults (``api:<ip>``, ``rest``, ``manual``,
``preset``/``custom``/``bridge``).

These tests use mock app.state to isolate the header-extraction logic
from real device side-effects.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from backend.api.auth import source_from_request


def _real_request(
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
    method: str = "POST",
    path: str = "/test",
) -> Request:
    """Build a real Starlette Request — the rate-limit decorator on the
    automation routes does an isinstance(Request) check that rejects
    MagicMock-based fakes."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "client": (client_host, 0),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def _request(headers: dict[str, str] | None = None) -> Request:
    """Minimal real Request for source_from_request unit tests."""
    return _real_request(headers=headers)


# ---------------------------------------------------------------------------
# source_from_request — unit tests on the helper directly
# ---------------------------------------------------------------------------

class TestSourceFromRequest:
    def test_header_present_overrides_fallback(self):
        req = _request({"X-Source": "alexa:SetModeIntent"})
        assert source_from_request(req, "api:127.0.0.1") == "alexa:SetModeIntent"

    def test_header_missing_uses_fallback(self):
        req = _request({})
        assert source_from_request(req, "api:127.0.0.1") == "api:127.0.0.1"

    def test_empty_header_uses_fallback(self):
        # A misbehaving client setting `X-Source: ""` shouldn't tag every
        # row as the empty string — fall back instead.
        req = _request({"X-Source": ""})
        assert source_from_request(req, "rest") == "rest"

    def test_whitespace_only_header_uses_fallback(self):
        req = _request({"X-Source": "   "})
        assert source_from_request(req, "manual") == "manual"

    def test_strips_surrounding_whitespace(self):
        req = _request({"X-Source": "  alexa:Foo  "})
        assert source_from_request(req, "fallback") == "alexa:Foo"


# ---------------------------------------------------------------------------
# Integration — routes propagate X-Source to engine / event_logger calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_override_route_threads_header_to_set_manual_override():
    """POST /api/automation/override with X-Source: alexa:SetModeIntent
    should call engine.set_manual_override(..., source='alexa:SetModeIntent')."""
    from backend.api.routes.automation import set_override
    from backend.api.schemas.automation import ManualOverride

    captured: dict[str, str] = {}
    engine = MagicMock()
    engine.set_manual_override = AsyncMock(
        side_effect=lambda mode, source: captured.update({"mode": mode, "source": source})
    )

    request = _real_request(headers={"X-Source": "alexa:SetModeIntent"})
    request.scope["app"] = MagicMock()
    request.scope["app"].state.automation = engine
    # slowapi reads request.app.state.limiter; init_limiter sets it on
    # the real app — for these unit tests we wire a noop limiter.
    request.scope["app"].state.limiter = None

    await set_override(ManualOverride(mode="relax"), request)
    assert captured["source"] == "alexa:SetModeIntent"


@pytest.mark.asyncio
async def test_override_route_marks_auto_as_explicit_user_intent():
    """The route, not generic clear callers, owns Sleeping→Auto wake intent."""
    from backend.api.routes.automation import set_override
    from backend.api.schemas.automation import ManualOverride

    engine = MagicMock()
    engine.clear_override = AsyncMock()
    away_manager = MagicMock()
    away_manager.reacquire_home_after_auto = AsyncMock()

    request = _real_request(headers={}, client_host="192.168.1.30")
    request.scope["app"] = MagicMock()
    request.scope["app"].state.automation = engine
    request.scope["app"].state.away_manager = away_manager
    request.scope["app"].state.limiter = None

    await set_override(ManualOverride(mode="auto"), request)

    engine.clear_override.assert_awaited_once_with(
        source="api:192.168.1.30",
        user_requested_auto=True,
    )
    away_manager.reacquire_home_after_auto.assert_awaited_once_with(
        source="api:192.168.1.30",
    )


@pytest.mark.asyncio
async def test_override_route_falls_back_to_api_ip():
    """No X-Source → falls back to api:<remote_ip> (preserves existing
    dashboard / curl behavior)."""
    from backend.api.routes.automation import set_override
    from backend.api.schemas.automation import ManualOverride

    captured: dict[str, str] = {}
    engine = MagicMock()
    engine.set_manual_override = AsyncMock(
        side_effect=lambda mode, source: captured.update({"source": source})
    )

    request = _real_request(headers={}, client_host="192.168.1.30")
    request.scope["app"] = MagicMock()
    request.scope["app"].state.automation = engine
    request.scope["app"].state.limiter = None

    await set_override(ManualOverride(mode="relax"), request)
    assert captured["source"] == "api:192.168.1.30"


@pytest.mark.asyncio
async def test_dnd_enable_route_threads_header():
    from backend.api.routes.automation import enable_dnd_route
    from backend.api.schemas.automation import DNDRequest

    captured: dict[str, str] = {}
    engine = MagicMock()
    engine.enable_dnd = AsyncMock(
        side_effect=lambda mins, source: captured.update({"source": source}) or {}
    )

    request = _real_request(headers={"X-Source": "alexa:EnableDNDIntent"})
    request.scope["app"] = MagicMock()
    request.scope["app"].state.automation = engine
    request.scope["app"].state.limiter = None

    await enable_dnd_route(DNDRequest(duration_minutes=60), request)
    assert captured["source"] == "alexa:EnableDNDIntent"


@pytest.mark.asyncio
async def test_sonos_log_helper_threads_header():
    """`_log_manual_sonos` should pass the X-Source value through to
    `event_logger.log_sonos_event(triggered_by=...)`."""
    from backend.api.routes.sonos import _log_manual_sonos

    captured: dict[str, str] = {}
    event_logger = MagicMock()
    event_logger.log_sonos_event = AsyncMock(
        side_effect=lambda **kw: captured.update(kw)
    )
    automation = MagicMock()
    automation.current_mode = "gaming"

    request = MagicMock()
    request.app.state.event_logger = event_logger
    request.app.state.automation = automation
    request.headers = {"X-Source": "alexa:NextTrackIntent"}

    await _log_manual_sonos(request, "skip")

    assert captured["triggered_by"] == "alexa:NextTrackIntent"


@pytest.mark.asyncio
async def test_sonos_log_helper_falls_back_to_manual():
    from backend.api.routes.sonos import _log_manual_sonos

    captured: dict[str, str] = {}
    event_logger = MagicMock()
    event_logger.log_sonos_event = AsyncMock(
        side_effect=lambda **kw: captured.update(kw)
    )
    automation = MagicMock()
    automation.current_mode = "gaming"

    request = MagicMock()
    request.app.state.event_logger = event_logger
    request.app.state.automation = automation
    request.headers = {}

    await _log_manual_sonos(request, "play")

    assert captured["triggered_by"] == "manual"
