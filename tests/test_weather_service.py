"""
Tests for the weather service — caching, response parsing, error handling.

Mocks httpx to avoid real API calls. Targets the NWS-based WeatherService
(replaced OpenWeatherMap integration for free severe-weather alerts).
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.weather_service import CACHE_TTL, WeatherService

# Fixtures matching NWS API response shapes.
# get_current() fires 4 sequential client.get calls in this order:
#   1. observations  2. forecast  3. alerts  4. sunrise-sunset
NWS_OBS_RESPONSE = {
    "properties": {
        "temperature": {"value": 22.2},   # °C → 71.96°F → round 72
        "relativeHumidity": {"value": 45},
        "windSpeed": {"value": 13.0},      # km/h → 8 mph
        "heatIndex": {"value": None},
        "windChill": {"value": None},
        "textDescription": "Clear",
    },
}

NWS_FORECAST_RESPONSE = {
    "properties": {"periods": []},         # no daily high/low data
}

NWS_ALERTS_RESPONSE = {"features": []}    # no active alerts

SUNRISE_RESPONSE = {
    "status": "OK",
    "results": {
        "sunrise": "2026-04-16T11:00:00+00:00",
        "sunset":  "2026-04-16T23:00:00+00:00",
    },
}


def _make_service():
    return WeatherService()


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


def _mock_client(responses: list[dict] | Exception) -> AsyncMock:
    """Build an AsyncClient mock whose .get() returns each response in order (or raises)."""
    client = AsyncMock()
    if isinstance(responses, Exception):
        client.get = AsyncMock(side_effect=responses)
    else:
        client.get = AsyncMock(side_effect=[_mock_response(r) for r in responses])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

class TestCaching:
    """Verify cache TTL behavior."""

    async def test_returns_cache_when_fresh(self):
        svc = _make_service()
        svc._cache = {"temp": 72, "cached": True}
        svc._cache_time = time.time()  # just now
        result = await svc.get_current()
        assert result["cached"] is True  # returned without HTTP call

    async def test_cache_expired_triggers_fetch(self):
        svc = _make_service()
        svc._cache = {"temp": 72, "old": True}
        svc._cache_time = time.time() - CACHE_TTL - 1  # expired

        client = _mock_client([
            NWS_OBS_RESPONSE,
            NWS_FORECAST_RESPONSE,
            NWS_ALERTS_RESPONSE,
            SUNRISE_RESPONSE,
        ])

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_current()
        assert result is not None
        assert result["temp"] == 72
        assert "old" not in result

    async def test_stale_cache_returned_on_failure(self):
        svc = _make_service()
        svc._cache = {"temp": 72, "stale": True}
        svc._cache_time = time.time() - CACHE_TTL - 1  # expired

        client = _mock_client(Exception("network error"))

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_current()
        assert result["stale"] is True

    async def test_no_cache_no_api_returns_none(self):
        svc = _make_service()

        client = _mock_client(Exception("network error"))

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_current()
        assert result is None

    def test_get_cached_returns_none_initially(self):
        svc = _make_service()
        assert svc.get_cached() is None

    def test_get_cached_returns_stored_data(self):
        svc = _make_service()
        svc._cache = {"temp": 72}
        assert svc.get_cached() == {"temp": 72}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestResponseParsing:
    """Verify fields are correctly extracted from NWS responses."""

    async def test_parses_all_fields(self):
        svc = _make_service()

        client = _mock_client([
            NWS_OBS_RESPONSE,
            NWS_FORECAST_RESPONSE,
            NWS_ALERTS_RESPONSE,
            SUNRISE_RESPONSE,
        ])

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_current()

        assert result["temp"] == 72                     # 22.2°C → 72°F
        assert result["feels_like"] == 72               # no heat/wind chill → falls through to temp_f
        assert result["description"] == "Clear"
        assert result["icon"].startswith("01")          # clear → 01d or 01n depending on wall-clock
        assert result["humidity"] == 45
        assert result["wind_speed"] == 8                # 13 km/h → 8 mph
        assert result["city"] == "Indianapolis"
        assert result["sunrise"] is not None
        assert result["sunset"] is not None
