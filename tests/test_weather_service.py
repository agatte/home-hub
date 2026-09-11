"""
Tests for the weather service — caching, response parsing, error handling.

Mocks httpx to avoid real API calls. Targets the NWS-based WeatherService
(replaced OpenWeatherMap integration for free severe-weather alerts).
"""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.weather_service import (
    ALERT_ACTUATOR_GRACE_SECONDS,
    CACHE_TTL,
    OBSERVATION_FRESHNESS_MAX_SECONDS,
    OBSERVATION_FUTURE_SKEW_SECONDS,
    WeatherService,
)

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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    svc = WeatherService(latitude=40.0, longitude=-86.0)
    # Keep legacy unit tests on their original four-call fetch sequence while
    # the dedicated foundation tests exercise NWS /points discovery.
    svc._forecast_url = "https://api.weather.gov/gridpoints/IND/58,69/forecast"
    svc._stations_url = "https://api.weather.gov/gridpoints/IND/58,69/stations"
    svc._point_stations = ["KIND"]
    svc._point_metadata_time = time.time()
    return svc


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

    async def test_nws_http_client_follows_redirects(self):
        svc = _make_service()
        client = _mock_client(Exception("stop after client construction"))
        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client) as ctor:
            await svc.get_current()
        assert ctor.call_args.kwargs["follow_redirects"] is True

    def test_get_cached_returns_none_initially(self):
        svc = _make_service()
        assert svc.get_cached() is None

    def test_get_cached_returns_stored_data(self):
        svc = _make_service()
        svc._cache = {"temp": 72}
        assert svc.get_cached() == {"temp": 72}

    def test_cache_snapshot_does_not_infer_source_freshness_from_fetch_age(self):
        svc = _make_service()
        svc._cache = {"description": "Clear"}
        svc._cache_time = time.time() - 10
        snapshot = svc.get_cache_snapshot()
        assert snapshot["condition"] == "Clear"
        assert snapshot["fresh"] is False
        assert snapshot["actuator_usable"] is False
        assert 9 <= snapshot["age_seconds"] <= 11
        assert snapshot["stale_fallback"] is False

    def test_cache_snapshot_marks_stale_fallback(self):
        svc = _make_service()
        svc._cache = {"description": "Rain"}
        svc._cache_time = time.time() - CACHE_TTL - 1
        svc._cache_is_stale_fallback = True
        snapshot = svc.get_cache_snapshot()
        assert snapshot["fresh"] is False
        assert snapshot["stale_fallback"] is True

    def test_cache_snapshot_rejects_far_future_source_for_actuation(self):
        svc = _make_service()
        svc._cache = {"description": "Clear", "temp": 72}
        svc._source_observation_at = datetime.now(timezone.utc) + timedelta(
            seconds=OBSERVATION_FUTURE_SKEW_SECONDS + 1
        )
        snapshot = svc.get_cache_snapshot()
        assert snapshot["fresh"] is False
        assert snapshot["actuator_usable"] is False
        assert snapshot["provenance"] == "stale_display"
        assert svc.get_actuator_context() is None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestResponseParsing:
    """Verify fields are correctly extracted from NWS responses."""

    async def test_parses_all_fields(self):
        svc = WeatherService(latitude=40.0, longitude=-86.0)
        observation = {
            **NWS_OBS_RESPONSE,
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        client = _mock_client([
            {"properties": {
                "forecast": "https://api.weather.gov/gridpoints/IND/58,69/forecast",
                "forecastGridData": "https://api.weather.gov/gridpoints/IND/58,69",
                "observationStations": "https://api.weather.gov/gridpoints/IND/58,69/stations",
                "gridId": "IND",
                "gridX": 58,
                "gridY": 69,
            }},
            {"features": [{"properties": {"stationIdentifier": "KIND"}}]},
            observation,
            NWS_FORECAST_RESPONSE,
            {"properties": {"skyCover": {"values": [{"value": 75, "validTime": f"{datetime.now(timezone.utc).isoformat()}/PT1H"}]}}},
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
        context = svc.get_actuator_context()
        assert context["station_id"] == "KIND"
        assert context["sky_cover"]["value"] == 75
        snapshot = svc.get_cache_snapshot()
        assert snapshot["grid_id"] == "IND"
        assert snapshot["grid_x"] == 58
        assert snapshot["grid_y"] == 69
        assert snapshot["gridpoint"] == "IND 58,69"


class TestWeatherFoundation:
    def test_coordinates_must_be_paired(self):
        with pytest.raises(ValueError, match="configured together"):
            WeatherService(latitude=40.0)

    def test_actuator_context_rejects_stale_source_but_keeps_display_data(self):
        svc = _make_service()
        svc._cache = {"description": "Clear", "temp": 72}
        svc._source_observation_at = datetime.fromtimestamp(
            time.time() - OBSERVATION_FRESHNESS_MAX_SECONDS - 1,
            tz=timezone.utc,
        )
        assert svc.get_cached()["temp"] == 72
        assert svc.get_actuator_context() is None

    def test_active_severe_alert_can_supply_context_without_fresh_observation(self):
        svc = _make_service()
        svc._alert_cache = [{
            "event": "Tornado Warning",
            "severity": "Extreme",
            "expires": "2099-01-01T00:00:00+00:00",
        }]
        svc._alert_cache_time = time.time()
        assert svc.get_actuator_context()["weather"]["description"] == "thunderstorm"

    async def test_preferred_station_is_tried_before_point_station(self):
        svc = WeatherService(
            latitude=40.0,
            longitude=-86.0,
            preferred_stations="KUMP",
        )
        observation = {
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        client = _mock_client([
            {"properties": {
                "forecast": "https://api.weather.gov/gridpoints/IND/58,69/forecast",
                "forecastGridData": "https://api.weather.gov/gridpoints/IND/58,69",
                "observationStations": "https://api.weather.gov/gridpoints/IND/58,69/stations",
            }},
            {"features": [{"properties": {"stationIdentifier": "KIND"}}]},
            observation,
        ])
        result = await svc._fetch_observations(client)
        assert result == observation
        assert "KUMP" in client.get.await_args_list[2].args[0]

    async def test_invalid_point_urls_are_rejected(self):
        svc = WeatherService(latitude=40.0, longitude=-86.0)
        client = _mock_client([{"properties": {
            "forecast": "https://example.invalid/forecast",
            "forecastGridData": "https://api.weather.gov/gridpoints/IND/58,69",
            "observationStations": "https://api.weather.gov/gridpoints/IND/58,69/stations",
        }}])
        assert await svc._ensure_point_metadata(client) is False

    async def test_alert_refresh_empty_response_clears_immediately(self):
        svc = WeatherService(latitude=40.0, longitude=-86.0)
        svc._alert_cache = [{"id": "old", "event": "Flood Warning"}]
        client = _mock_client([NWS_ALERTS_RESPONSE])
        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            assert await svc.refresh_alerts() == []
        assert svc.get_cached_alerts() == []

    async def test_alert_refresh_failure_keeps_only_locally_active_alerts(self):
        svc = WeatherService(latitude=40.0, longitude=-86.0)
        svc._alert_cache = [
            {"event": "Flood Warning", "expires": "2099-01-01T00:00:00+00:00"},
            {"event": "Flood Warning", "expires": "2000-01-01T00:00:00+00:00"},
        ]
        client = _mock_client(Exception("network error"))
        with patch("backend.services.weather_service.httpx.AsyncClient", return_value=client):
            alerts = await svc.refresh_alerts()
        assert alerts == [svc._alert_cache[0]]


    def test_unconfigured_service_is_neutral(self):
        svc = WeatherService()
        assert svc.get_cached() is None
        assert svc.get_actuator_context() is None

    async def test_unconfigured_start_spawns_no_background_tasks(self):
        svc = WeatherService()
        await svc.start()
        assert svc._background_tasks == []

    def test_severe_alert_outranks_fresh_ordinary_observation(self):
        svc = _make_service()
        svc._cache = {"description": "Clear", "temp": 72, "icon": "01d"}
        svc._source_observation_at = datetime.now(timezone.utc)
        svc._alert_cache = [{
            "event": "Severe Thunderstorm Warning",
            "severity": "Severe",
            "expires": "2099-01-01T00:00:00+00:00",
        }]
        svc._alert_cache_time = time.time()
        context = svc.get_actuator_context()
        assert context["provenance"] == "home_point_alert"
        assert context["weather"]["description"] == "thunderstorm"

    def test_clearing_alert_restores_raw_observation_projection(self):
        svc = _make_service()
        svc._cache = {"description": "Clear", "temp": 72, "icon": "01d"}
        svc._alert_cache = [{
            "event": "Tornado Warning",
            "severity": "Extreme",
            "expires": "2099-01-01T00:00:00+00:00",
        }]
        svc._alert_cache_time = time.time()
        assert svc.get_cached()["description"] == "thunderstorm"
        svc._alert_cache = []
        assert svc.get_cached()["description"] == "Clear"

    def test_twenty_minute_airport_observation_is_fresh(self):
        observed = datetime.fromtimestamp(time.time() - 20 * 60, tz=timezone.utc)
        observation = {
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": observed.isoformat(),
            }
        }
        assert WeatherService._observation_is_usable(observation, observed) is True

    def test_observation_older_than_freshness_boundary_is_rejected(self):
        observed = datetime.fromtimestamp(
            time.time() - OBSERVATION_FRESHNESS_MAX_SECONDS - 1,
            tz=timezone.utc,
        )
        observation = {
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": observed.isoformat(),
            }
        }
        assert WeatherService._observation_is_usable(observation, observed) is False

    async def test_stale_preferred_station_falls_back_to_point_station(self):
        svc = WeatherService(
            latitude=40.0,
            longitude=-86.0,
            preferred_stations="KUMP",
        )
        svc._forecast_url = "https://api.weather.gov/gridpoints/IND/58,69/forecast"
        svc._stations_url = "https://api.weather.gov/gridpoints/IND/58,69/stations"
        svc._point_stations = ["KIND"]
        svc._point_metadata_time = time.time()
        stale = {
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": datetime.fromtimestamp(
                    time.time() - OBSERVATION_FRESHNESS_MAX_SECONDS - 1,
                    tz=timezone.utc,
                ).isoformat(),
            }
        }
        fresh = {
            "properties": {
                **NWS_OBS_RESPONSE["properties"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        }
        client = _mock_client([stale, fresh])
        result = await svc._fetch_observations(client)
        assert result == fresh
        assert svc._station_id == "KIND"


    def test_cache_snapshot_exposes_canonical_family_and_alert_provenance(self):
        svc = _make_service()
        svc._cache = {"description": "Partly Cloudy", "temp": 72, "icon": "02d"}
        svc._source_observation_at = datetime.now(timezone.utc)
        base = svc.get_cache_snapshot()
        assert base["condition_family"] == "clouds"
        assert base["provenance"] == "station_observation"
        assert base["actuator_usable"] is True
        svc._alert_cache = [{
            "event": "Tornado Warning",
            "severity": "Extreme",
            "expires": "2099-01-01T00:00:00+00:00",
        }]
        svc._alert_cache_time = time.time()
        alert = svc.get_cache_snapshot()
        assert alert["condition"] == "thunderstorm"
        assert alert["condition_family"] == "thunderstorm"
        assert alert["severe_alert_override"] == "thunderstorm"
        assert alert["provenance"] == "home_point_alert"


    def test_stale_alert_feed_is_display_only_not_actuator_authority(self):
        svc = _make_service()
        svc._alert_cache = [{
            "event": "Tornado Warning", "severity": "Extreme",
            "expires": "2099-01-01T00:00:00+00:00",
        }]
        svc._alert_cache_time = time.time() - ALERT_ACTUATOR_GRACE_SECONDS - 1
        assert svc.get_cached_alerts()
        assert svc.get_cached() is None
        assert svc.get_actuator_context() is None
        snapshot = svc.get_cache_snapshot()
        assert snapshot["display_severe_alert_override"] == "thunderstorm"
        assert snapshot["severe_alert_override"] is None
        assert snapshot["alert_actuator_usable"] is False

    def test_sky_cover_requires_interval_covering_now(self):
        now = datetime.now(timezone.utc)
        values = [{"value": 75, "validTime": "2000-01-01T00:00:00+00:00/PT1H"}, {"value": 60}]
        assert WeatherService._select_grid_value(values, now) is None


# --- Alert novelty dedup (#26) -----------------------------------------------

def test_alert_novelty_emits_once_then_suppresses_then_refires():
    """Same active alert is novel once; a new id is novel; an expired alert that
    reappears is novel again (seen-set resets to the current active ids)."""
    svc = WeatherService()
    a = {"id": "urn:oid:a", "event": "Tornado Warning", "onset": None, "expires": None}
    b = {"id": "urn:oid:b", "event": "Flood Warning", "onset": None, "expires": None}

    # First sighting of `a` → novel.
    assert [x["id"] for x in svc._novel_alerts([a])] == ["urn:oid:a"]
    # Same alert still active next poll → suppressed (no re-emit).
    assert svc._novel_alerts([a]) == []
    # `b` joins while `a` persists → only `b` is novel.
    assert [x["id"] for x in svc._novel_alerts([a, b])] == ["urn:oid:b"]
    # Everything clears → nothing novel, and the seen-set empties.
    assert svc._novel_alerts([]) == []
    assert svc._seen_alert_ids == set()
    # `a` reappears after expiring → novel again.
    assert [x["id"] for x in svc._novel_alerts([a])] == ["urn:oid:a"]


def test_alert_id_composite_fallback_when_feature_has_no_id():
    """Alerts lacking an NWS id fall back to an event|onset|expires composite,
    which is still stable across polls (so they don't re-spam)."""
    svc = WeatherService()
    a = {"event": "Heat Advisory", "onset": "2026-06-01T12:00", "expires": "2026-06-01T20:00"}
    assert [x["event"] for x in svc._novel_alerts([a])] == ["Heat Advisory"]
    assert svc._novel_alerts([a]) == []  # composite id stable → suppressed
