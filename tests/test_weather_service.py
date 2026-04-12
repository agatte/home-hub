"""
Tests for the weather service — caching, response parsing, error handling.

Mocks httpx to avoid real API calls.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.weather_service import CACHE_TTL, WeatherService

# Sample API responses
CURRENT_RESPONSE = {
    "main": {"temp": 72.5, "feels_like": 70.1, "temp_min": 68, "temp_max": 75, "humidity": 45},
    "weather": [{"description": "clear sky", "icon": "01d"}],
    "wind": {"speed": 8.3},
    "sys": {"sunrise": 1712916000, "sunset": 1712962800},
    "name": "Indianapolis",
}


def _make_service():
    return WeatherService(api_key="test-key", city="Indianapolis,US")


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

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = CURRENT_RESPONSE

        mock_forecast_resp = MagicMock()
        mock_forecast_resp.status_code = 200
        mock_forecast_resp.raise_for_status = MagicMock()
        mock_forecast_resp.json.return_value = {"list": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp, mock_forecast_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc.get_current()
        assert result is not None
        assert result["temp"] == 72  # round(72.5) = 72 (banker's rounding)
        assert "old" not in result

    async def test_stale_cache_returned_on_failure(self):
        svc = _make_service()
        svc._cache = {"temp": 72, "stale": True}
        svc._cache_time = time.time() - CACHE_TTL - 1  # expired

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc.get_current()
        assert result["stale"] is True

    async def test_no_cache_no_api_returns_none(self):
        svc = _make_service()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=mock_client):
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
    """Verify fields are correctly extracted from OWM response."""

    async def test_parses_all_fields(self):
        svc = _make_service()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = CURRENT_RESPONSE

        mock_forecast_resp = MagicMock()
        mock_forecast_resp.status_code = 200
        mock_forecast_resp.raise_for_status = MagicMock()
        mock_forecast_resp.json.return_value = {"list": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp, mock_forecast_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc.get_current()

        assert result["temp"] == 72  # round(72.5) = 72 (banker's rounding)
        assert result["feels_like"] == 70
        assert result["description"] == "clear sky"
        assert result["icon"] == "01d"
        assert result["humidity"] == 45
        assert result["wind_speed"] == 8
        assert result["city"] == "Indianapolis"
        assert "sunrise" in result
        assert "sunset" in result
